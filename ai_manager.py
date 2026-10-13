"""
ai_manager.py -- the AI processing layer (the app's "core engine").

Pipeline: io_manager -> ai_manager -> logic_manager -> data_manager.
For one maintenance check: build_prompt -> call the AI -> parse_response ->
validate_response; process() runs all four and is what main.py calls.
Gemini (manual PDF attached) is the main AI; Groq (text excerpt of the manual)
is the backup; if both fail, FALLBACK_ASSESSMENT -> "NEEDS MANUAL REVIEW".
No business rules here, and errors go to the log, never print().
See explanations/ai_manager_explained.txt for a full walkthrough.
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
    # C4: temperature 0 removes randomness, so the same check gets the same answer.
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
    """Build the prompt for one maintenance check from the record's details.
    Returns the prompt text (fixed 1-10 scale, JSON-only reply requested)."""
    # The fixed urgency scale lines up with the thresholds in logic_manager.route.
    # C3: the reply format below must match REQUIRED_KEYS.
    return (
        "You are an automotive maintenance advisor in Singapore. The owner's "
        "manual for this car is attached. Using that manual as your main "
        "source, assess how urgently one part needs servicing.\n\n"
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
        f"- Our stored schedule: every {record.get('interval_km')} km or "
        f"{record.get('interval_months')} months, whichever comes first\n"
        f"- Last serviced: {record.get('last_service_date')} at "
        f"{record.get('last_service_mileage')} km\n"
        f"- Today: {record.get('check_date')}, odometer {record.get('current_odometer')} km\n\n"
        "STEPS\n"
        "1. Find what the manual says about this part: its replacement or "
        "inspection interval, and any 'severe driving conditions' schedule "
        "(Singapore's heat and stop-and-go traffic usually count as severe).\n"
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
        "'replace', unclear normal vs severe), or disagrees with our stored schedule\n"
        "   Low     the manual does not cover this part; you used general knowledge\n\n"
        "Reply with ONLY one JSON object, exactly these keys:\n"
        "{\n"
        '  "urgency_score": <integer 1-10>,\n'
        '  "confidence": <"High", "Medium" or "Low">,\n'
        '  "overdue_summary": <one short sentence such as "Engine oil: 650 km overdue" '
        'or "Tyres: 12 days overdue" or "Air filter: 3,000 km remaining">,\n'
        '  "recommended_action": <one short sentence telling the owner what to do next>,\n'
        '  "manual_reference": <where in the manual you found this, e.g. '
        '"Maintenance schedule, p. 7", or "Not covered in manual">\n'
        "}"
    )


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

def validate_response(data: dict | None) -> dict | None:
    """C3: check the parsed answer against the schema before anything uses it.
    Returns a clean copy with ai_status "ok", or None to reject it."""
    if not isinstance(data, dict):
        return None

    for key in REQUIRED_KEYS:
        if key not in data:
            logger.error("AI response is missing %r: %s", key, data)
            return None

    # urgency_score must be an int 1-10. 7.0 is accepted as 7; True/False are
    # rejected explicitly because Python treats bool as a kind of int.
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

    # Only the expected keys are copied; any extra keys from the AI are dropped.
    return {
        "urgency_score": score,
        "confidence": data["confidence"],
        "overdue_summary": data["overdue_summary"],
        "recommended_action": data["recommended_action"],
        "manual_reference": data["manual_reference"],
        "ai_status": "ok",
    }
