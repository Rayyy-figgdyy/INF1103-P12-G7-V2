"""
ai_manager.py -- the AI processing layer (the app's "core engine").

Pipeline: io_manager -> ai_manager -> logic_manager -> data_manager.
For one maintenance check: build_prompt -> call the AI -> parse_response ->
validate_response; process() runs all four and is what main.py calls.

Gemini (manual PDF attached) is the main AI; Groq (text excerpt of the manual)
is the backup; if both fail, FALLBACK_ASSESSMENT -> "NEEDS MANUAL REVIEW".

No business rules here, and errors go to the log, never print().
"""
import json
import logging
import os
import time

import pdfplumber
from dotenv import load_dotenv
from google import genai
from groq import Groq

logger = logging.getLogger("ai_manager")

# ======================================================================
# FIXED SETTINGS
# ======================================================================

# Either model can be overridden with GEMINI_MODEL / GROQ_MODEL in .env.
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
API_TIMEOUT_SECONDS = 60
RETRY_DELAY_SECONDS = 3      # pause before retrying when neither AI replied

GEMINI_CONFIG = {
    # C4: temperature 0 reduces response variability; repeated saved checks reuse stored results.
    "temperature": 0,
    # C3: ask for a JSON-only reply so parse_response() can read it.
    "response_mime_type": "application/json",
    # The SDK can run our Python functions for the AI; we pass none, so it is
    # switched off and the AI only answers the question.
    "automatic_function_calling": {"disable": True},
}

# Groq's free tier rejects oversized requests (error 413, about 8,000 tokens),
# so Groq gets only the manual lines about the part, capped at this many characters.
MAX_MANUAL_CHARS = 8_000
GROQ_MAX_ANSWER_TOKENS = 2048

# What each part is called in our manuals (US-style ones say "tire", "air cleaner").
# Used in the prompt and to find the relevant manual lines for Groq.
PART_SEARCH_WORDS = {
    "Engine Oil":        ["engine oil", "oil filter", "oil and filter"],
    "Brake Pads":        ["brake pad", "brake disc", "brakes"],
    "Spark Plugs":       ["spark plug"],
    "Tyres":             ["tyre", "tire rotation", "tires", "rotate"],
    "Engine Air Filter": ["air cleaner", "air filter"],
    "Coolant":           ["coolant", "cooling system"],
}

# C3: the JSON schema every AI answer must match (checked in validate_response).
REQUIRED_KEYS = ("urgency_score", "confidence", "overdue_summary",
                 "recommended_action", "manual_reference")
VALID_CONFIDENCE = ("High", "Medium", "Low")

# Used when no AI gives a valid answer. ai_status != "ok" makes logic_manager.route
# return "NEEDS MANUAL REVIEW", so the app carries on instead of crashing.
FALLBACK_ASSESSMENT = {
    "urgency_score": None,
    "confidence": "Unknown",
    "overdue_summary": "AI assessment unavailable.",
    "recommended_action": "Could not get an AI recommendation -- check this part manually.",
    "manual_reference": "n/a",
    "ai_provider": "none",
    "ai_status": "unavailable",
}


# ======================================================================
# CONNECTING TO THE TWO AI SERVICES
# ======================================================================

def get_clients() -> tuple:
    """Create the Gemini and Groq clients from the API keys in .env.
    Returns (gemini, groq); either is None if its key is missing."""
    load_dotenv()
    gemini_key = os.environ.get("GEMINI_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")

    gemini = None
    if gemini_key:
        # Gemini takes its timeout in milliseconds; Groq (below) takes seconds.
        gemini = genai.Client(api_key=gemini_key,
                              http_options={"timeout": API_TIMEOUT_SECONDS * 1000})
    else:
        logger.error("GEMINI_API_KEY is not set -- copy .env.example to .env and add your key.")

    # A missing Groq key is not logged: Groq is only the backup.
    groq = None
    if groq_key:
        groq = Groq(api_key=groq_key, timeout=API_TIMEOUT_SECONDS)

    return gemini, groq


# ======================================================================
# STEP 1: build_prompt
# ======================================================================

def build_prompt(record: dict) -> str:
    """Build one AI prompt using the manual baseline and any eligible brake history."""
    # The fixed urgency scale lines up with the thresholds in logic_manager.route.
    prompt = (
        "You are an automotive maintenance advisor in Singapore. The owner's "
        "manual for this car is attached. Use the manual as the authoritative "
        "maintenance baseline and assess how urgently one part needs servicing.\n\n"
        "VEHICLE\n"
        f"- Model: {record.get('car_model')}\n"
        f"- Condition when bought: {record.get('car_condition')}\n"
        f"- COE expiry date: {record.get('coe_expiry_date')}\n\n"
        "PART\n"
        f"- Part: {record.get('part_name')}\n"
        f"- The manual may call it: "
        f"{', '.join(PART_SEARCH_WORDS.get(record.get('part_name'), [str(record.get('part_name'))]))}\n"
        "- For Tyres, the service interval means the tyre ROTATION interval; "
        "also consider the manual's tread-wear and inspection advice.\n"
        f"- Our stored schedule (from the manual's normal schedule; 0 = the manual gives "
        f"no limit of that kind): {record.get('action', 'replace')} every "
        f"{record.get('interval_km')} km or {record.get('interval_months')} months, "
        f"whichever comes first"
        f"{' (first change of this part)' if record.get('interval_stage') == 'first' else ''}"
        f"{' (interval after the first change)' if record.get('interval_stage') == 'repeat' else ''}\n"
        f"- Last serviced: {record.get('last_service_date')} at "
        f"{record.get('last_service_mileage')} km"
        f"{' (never replaced: counted from the car being new)' if record.get('last_service_mileage') == 0 and record.get('service_id') is None else ''}\n"
        f"- Today: {record.get('check_date')}, odometer {record.get('current_odometer')} km\n\n"
        "STEPS\n"
        "1. Find what the manual's NORMAL schedule says about this part: its replacement or "
        "inspection interval. For this project, use only the normal schedule. Do not use or "
        "mention severe-driving schedules, and do not infer a severe schedule from Singapore "
        "weather or traffic.\n"
        "2. Compare the distance AND time since the last service with that interval.\n"
        "3. Score urgency with this scale:\n"
        "   1-3  well within the interval (under 70% of distance and time used)\n"
        "   4-5  approaching the interval (70-100% used)\n"
        "   6-7  at or just past the interval, part not safety-critical\n"
        "   8-9  clearly overdue, or a safety-critical part (brake pads, "
        "tyres) at or past its interval\n"
        "   10   safety-critical and far overdue: do not drive until serviced\n"
        "   For a used car, the earlier service history is unknown, so lean "
        "one point higher when unsure.\n"
        "4. Set confidence:\n"
        "   High    the manual states an interval for this exact part and you used it\n"
        "   Medium  the manual only covers it indirectly (e.g. 'inspect' not "
        "'replace'), or disagrees with our stored normal schedule\n"
        "   Low     the manual does not cover this part; you used general knowledge\n\n"
    )

    history = record.get("brake_pad_history")
    if record.get("part_name") == "Brake Pads" and isinstance(history, list) and len(history) >= 3:
        prompt += (
            "PERSONALISED BRAKE-PAD HISTORY\n"
            # Provide every eligible history entry, including inspections.
            f"- Raw brake-pad servicing records: {json.dumps(history, ensure_ascii=False)}\n"
            "- These records passed the history eligibility checks. Consider all entries, "
            "but count ONLY service_action=replace as confirmed replacements.\n"
            "- Inspections provide context but do not count as replacements or reset a "
            "replacement interval; unknown actions are not confirmed replacements.\n"
            "- Calculate the replacement-to-replacement mileage intervals yourself.\n"
            "- Use the manual baseline AND this car's replacement pattern together to create "
            "ONE combined urgency_score. Do not create a separate history urgency score.\n"
            "- The manual remains authoritative. The history may add personalised context, "
            "but it must never be used to delay or ignore a manufacturer-required inspection "
            "or service.\n"
            "- Do not infer driving style, brake-pad thickness, or guaranteed remaining life.\n\n"
        )

    prompt += (
        "Reply with ONLY one JSON object with these required keys:\n"
        "{\n"
        '  "urgency_score": <integer 1-10>,\n'
        '  "confidence": <"High", "Medium" or "Low">,\n'
        '  "overdue_summary": <one short sentence such as "Engine oil: 650 km overdue" '
        'or "Tyres: 12 days overdue" or "Air filter: 3,000 km remaining">,\n'
        '  "recommended_action": <one short sentence telling the owner what to do next>,\n'
        '  "manual_reference": <where in the manual you found this, e.g. '
        '"Maintenance schedule, p. 7", or "Not covered in manual">'
    )
    if record.get("part_name") == "Brake Pads" and isinstance(history, list) and len(history) >= 3:
        prompt += ',\n  "history_pattern": <one short sentence describing the calculated replacement intervals>'
    prompt += "\n}"
    return prompt


# ======================================================================
# STEP 2: call_api (Gemini first, then Groq as backup)
# ======================================================================

def call_gemini(prompt: str, manual_path: str | None, client) -> str | None:
    """Send the prompt to Gemini with the manual PDF attached.
    Returns the reply text, or None on any error."""
    try:
        contents = [prompt]
        if manual_path:
            # The PDF is uploaded and attached so Gemini can read the whole manual
            # itself, and base its answer on this car's own service schedule.
            uploaded_manual = client.files.upload(file=manual_path)
            contents = [uploaded_manual, prompt]
        model = os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
        response = client.models.generate_content(model=model, contents=contents, config=GEMINI_CONFIG)
        return response.text
    except Exception as error:
        # Any failure (no network, bad key, 503 busy, 429 rate limit, timeout) is
        # logged and returns None, so ask_ai() moves on to the Groq backup.
        logger.error("Gemini call failed: %s", error)
        return None


def manual_text(manual_path: str) -> str:
    """Extract all text from the manual PDF (Groq cannot read PDF files).
    Returns the text, or "" if the PDF is unreadable or has no text layer."""
    try:
        page_texts = []
        with pdfplumber.open(manual_path) as pdf:
            for page in pdf.pages:
                page_texts.append(page.extract_text() or "")
        text = "\n".join(page_texts).strip()
    except Exception as error:
        logger.error("Could not read text from %s: %s", manual_path, error)
        return ""
    if not text:
        logger.warning("No text found in %s (is it a scanned image?).", manual_path)
    return text


def manual_excerpt(text: str, part_name: str) -> str:
    """Keep only the manual lines that mention the part (plus one line either side).
    Returns at most MAX_MANUAL_CHARS characters; uses the manual's start if no match."""
    # Parts not in PART_SEARCH_WORDS fall back to the words of their own name.
    if part_name in PART_SEARCH_WORDS:
        search_words = PART_SEARCH_WORDS[part_name]
    else:
        search_words = []
        for word in part_name.split():
            if len(word) > 2:
                search_words.append(word.lower().rstrip("s"))

    lines = text.splitlines()

    # Neighbouring lines are kept because schedule tables often wrap onto two lines.
    lines_to_keep = set()
    for line_number in range(len(lines)):
        line = lines[line_number].lower()
        for word in search_words:
            if word in line:
                lines_to_keep.update({line_number - 1, line_number, line_number + 1})

    kept_lines = []
    for line_number in sorted(lines_to_keep):
        if 0 <= line_number < len(lines):
            kept_lines.append(lines[line_number])

    excerpt = "\n".join(kept_lines)
    if not excerpt:
        excerpt = text
    # Size cap: stops Groq's free tier refusing the request with error 413.
    if len(excerpt) > MAX_MANUAL_CHARS:
        logger.warning("Manual text cut to %d characters for the backup AI.", MAX_MANUAL_CHARS)
        excerpt = excerpt[:MAX_MANUAL_CHARS]
    return excerpt


def call_groq(prompt: str, manual_path: str | None, client, part_name: str = "") -> str | None:
    """Send the prompt to Groq (backup AI) with a text excerpt of the manual in front.
    Returns the reply text, or None on any error."""
    content = prompt
    if manual_path:
        manual = manual_excerpt(manual_text(manual_path), part_name)
        if manual:
            content = ("OWNER'S MANUAL (the sections about this part, extracted from the PDF):\n"
                       + manual + "\n\n" + prompt)
        else:
            content = "(The owner's manual could not be read for this request.)\n\n" + prompt
    try:
        model = os.environ.get("GROQ_MODEL") or DEFAULT_GROQ_MODEL
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            temperature=0,                                     # C4: repeatable answers
            max_completion_tokens=GROQ_MAX_ANSWER_TOKENS,
            reasoning_effort="low",                            # stays within free-tier limits
            stream=False,
        )
        return response.choices[0].message.content
    except Exception as error:
        logger.error("Groq backup call failed: %s", error)
        return None


def ask_ai(prompt: str, manual_path: str | None, gemini, groq, part_name: str = "") -> tuple:
    """Ask Gemini first and fall back to Groq if Gemini gives no reply.
    Returns (reply text or None, "Gemini" / "Groq (backup)" / "none")."""
    if gemini is not None:
        reply = call_gemini(prompt, manual_path, gemini)
        if reply is not None:
            return reply, "Gemini"
    # Backup: only reached if Gemini has no client or returned None.
    if groq is not None:
        logger.warning("Gemini unavailable -- trying the Groq backup.")
        reply = call_groq(prompt, manual_path, groq, part_name)
        if reply is not None:
            return reply, "Groq (backup)"
    return None, "none"


def call_api(prompt: str, manual_path: str | None = None, client=None, backup_client=None) -> str | None:
    """Send the prompt (and manual) to the AI; the brief's call_api step.
    Returns the raw reply text, or None if every AI failed.
    client/backup_client are only passed in by tests; normally they come from .env."""
    # process() calls ask_ai() directly so it also learns which AI answered.
    # No part name is passed here, so a Groq fallback gets the start of the manual.
    if client is None and backup_client is None:
        client, backup_client = get_clients()
    reply, who_answered = ask_ai(prompt, manual_path, client, backup_client)
    return reply


# ======================================================================
# STEP 3: parse_response
# ======================================================================

def parse_response(reply: str | None) -> dict | None:
    """Extract the JSON object from the AI's reply text.
    Returns it as a dictionary, or None if there is no readable JSON object."""
    if not reply or not reply.strip():
        return None
    # Take the text from the first { to the last }, ignoring ```json fences or chatter.
    start = reply.find("{")
    end = reply.rfind("}")
    if start == -1 or end < start:
        logger.error("No JSON object in AI response: %r", reply[:200])
        return None
    try:
        data = json.loads(reply[start:end + 1])
    except json.JSONDecodeError as error:
        logger.error("AI response is not valid JSON: %s", error)
        return None
    if isinstance(data, dict):
        return data
    return None


# ======================================================================
# STEP 4: validate_response
# ======================================================================

def validate_response(data: dict | None, expect_history: bool = False) -> dict | None:
    """Validate one combined AI assessment before the rest of the app uses it."""
    if not isinstance(data, dict):
        return None

    for key in REQUIRED_KEYS:
        if key not in data:
            logger.error("AI response is missing %r: %s", key, data)
            return None

    # urgency_score must be an int 1-10. A whole-number float is accepted.
    score = data["urgency_score"]
    if isinstance(score, float) and score.is_integer():
        score = int(score)
    if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 10:
        logger.error("AI response has an invalid urgency_score: %r", data["urgency_score"])
        return None

    if data["confidence"] not in VALID_CONFIDENCE:
        logger.error("AI response has an invalid confidence: %r", data["confidence"])
        return None

    for key in ("overdue_summary", "recommended_action", "manual_reference"):
        value = data[key]
        if not isinstance(value, str) or not value.strip():
            logger.error("AI response has an empty or invalid %r: %r", key, value)
            return None

    answer = {
        "urgency_score": score,
        "confidence": data["confidence"],
        "overdue_summary": data["overdue_summary"],
        "recommended_action": data["recommended_action"],
        "manual_reference": data["manual_reference"],
        "ai_status": "ok",
    }

    # Eligible Brake Pad history is part of the same assessment, not a second different score.
    if expect_history:
        pattern = data.get("history_pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            logger.error("AI response is missing a valid brake history_pattern: %r", pattern)
            return None
        answer["history_pattern"] = pattern.strip()

    return answer


# ======================================================================
# process -- steps 1 to 4 for one check (called by main.py)
# ======================================================================

def process(record: dict, manual_path: str | None = None, client=None,
            backup_client=None, max_attempts: int = 2) -> dict:
    """Run every new maintenance check through AI, validating each provider's reply.
    If Gemini responds with malformed JSON, try Groq immediately instead of
    repeatedly asking Gemini for an unusable result."""
    if client is None and backup_client is None:
        client, backup_client = get_clients()

    prompt = build_prompt(record)
    history = record.get("brake_pad_history")
    expect_history = (record.get("part_name") == "Brake Pads"
                      and isinstance(history, list) and len(history) >= 3)

    for attempt in range(1, max_attempts + 1):
        # Check Gemini first, then validate its JSON before accepting the answer.
        if client is not None:
            reply = call_gemini(prompt, manual_path, client)
            answer = validate_response(parse_response(reply), expect_history=expect_history)
            if answer is not None:
                answer["ai_provider"] = "Gemini"
                result = dict(record)
                result.update(answer)
                return result

        # Even if Gemini returns text, invalid JSON or missing fields mean failure.
        # Groq gets its own chance to give a complete and valid response now.
        if backup_client is not None:
            logger.warning("No valid Gemini assessment -- trying Groq backup.")
            reply = call_groq(prompt, manual_path, backup_client,
                              record.get("part_name", ""))
            answer = validate_response(parse_response(reply), expect_history=expect_history)
            if answer is not None:
                answer["ai_provider"] = "Groq (backup)"
                result = dict(record)
                result.update(answer)
                return result

        logger.warning("Both AI providers failed validation (attempt %d of %d).",
                       attempt, max_attempts)
        if attempt < max_attempts:
            time.sleep(RETRY_DELAY_SECONDS)

    # All AI responses failed, so deterministic routing requests manual review.
    result = dict(record)
    result.update(FALLBACK_ASSESSMENT)
    return result