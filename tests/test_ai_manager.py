"""
Tests for ai_manager's classes with hardcoded sample AI responses and fake
clients -- no network, no API key. Covers the "malformed API response" and
"API connection failure" exception cases, plus the OOP design (abstract
AIProvider, polymorphic providers inside AIManager).

The fake clients are SimpleNamespace objects with the same methods the real
SDK clients have, so GeminiProvider/GroqProvider are tested unchanged.
"""
import json
from types import SimpleNamespace


from ai.ai_provider import AIProvider
from ai.gemini_provider import GeminiProvider
from ai.groq_provider import GroqProvider
from ai.manual_reader import ManualReader
from ai.prompt_builder import PromptBuilder
from ai.response_validator import ResponseValidator
from ai_manager import AIManager

GOOD = {
    "urgency_score": 7,
    "confidence": "High",
    "overdue_summary": "Engine oil: 650 km overdue",
    "recommended_action": "Book an oil change this week.",
    "manual_reference": "Maintenance schedule, p. 7",
}

GOOD_HISTORY = {
    **GOOD,
    "history_pattern": "Previous replacements were 20,000 km and 21,000 km apart.",
}

RECORD = {"part_name": "Engine Oil", "car_model": "Toyota Corolla 2020", "current_odometer": 50_650}

builder = PromptBuilder()
validator = ResponseValidator()


def fake_client(replies: list, calls: list):
    """A stand-in for genai.Client. Each generate_content() call returns the
    next reply; a reply that is an Exception is raised instead."""
    def generate_content(model, contents, config):
        calls.append(contents)
        reply = replies[min(len(calls), len(replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(text=reply)

    def upload(file):
        return f"<uploaded {file}>"

    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content),
                           files=SimpleNamespace(upload=upload))


def fake_groq(replies: list, calls: list):
    """A stand-in for the Groq client: chat.completions.create() returns the
    next reply; a reply that is an Exception is raised instead."""
    def create(model, messages, **kwargs):
        calls.append(messages[-1]["content"])
        reply = replies[min(len(calls), len(replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def manager(gemini_client=None, groq_client=None, max_attempts=2) -> AIManager:
    """An AIManager like from_env() builds, but with fake clients and no retry wait."""
    return AIManager([GeminiProvider(gemini_client), GroqProvider(groq_client)],
                     max_attempts=max_attempts, retry_delay=0)


# --- PromptBuilder ---------------------------------------------------------------

def test_prompt_includes_record_fields_and_asks_for_json():
    prompt = builder.build({**RECORD, "interval_km": 10_000, "interval_months": 6})
    assert "Engine Oil" in prompt and "10000 km" in prompt
    assert "JSON" in prompt and "urgency_score" in prompt


def test_prompt_tells_ai_to_use_the_manual_and_a_fixed_scale():
    prompt = builder.build(RECORD)
    assert "manual" in prompt.lower()
    assert "manual_reference" in prompt
    assert "8-9" in prompt and "High" in prompt  # urgency scale and confidence rules


# --- ResponseValidator.parse ---------------------------------------------------------

def test_parse_plain_json():
    assert validator.parse(json.dumps(GOOD)) == GOOD


def test_parse_json_inside_markdown_fence_and_extra_text():
    raw = "Sure! Here you go:\n```json\n" + json.dumps(GOOD) + "\n```\nHope that helps."
    assert validator.parse(raw) == GOOD


def test_parse_rejects_non_json():
    assert validator.parse("I think the oil is fine.") is None
    assert validator.parse("{not: valid json}") is None
    assert validator.parse("") is None
    assert validator.parse(None) is None


# --- ResponseValidator.validate ------------------------------------------------------

def test_validate_accepts_good_response():
    result = validator.validate(dict(GOOD))
    assert result["urgency_score"] == 7
    assert result["ai_status"] == "ok"


def test_validate_rejects_missing_key():
    for key in GOOD:
        bad = dict(GOOD)
        del bad[key]
        assert validator.validate(bad) is None, key


def test_validate_rejects_out_of_range_or_wrong_type_score():
    for bad_score in (0, 11, "7", True, 7.5, None):
        assert validator.validate({**GOOD, "urgency_score": bad_score}) is None


def test_validate_accepts_whole_number_float_score():
    assert validator.validate({**GOOD, "urgency_score": 7.0})["urgency_score"] == 7


def test_validate_combined_brake_result_requires_history_pattern():
    result = validator.validate(GOOD_HISTORY, expect_history=True)
    assert result["urgency_score"] == 7
    assert result["history_pattern"].startswith("Previous replacements")
    assert validator.validate(GOOD, expect_history=True) is None


def test_validate_rejects_unknown_confidence_and_empty_text():
    assert validator.validate({**GOOD, "confidence": "Very sure"}) is None
    assert validator.validate({**GOOD, "overdue_summary": "  "}) is None


# --- AIManager.process: retry and graceful failure ----------------------------------

def test_process_merges_ai_fields_into_record():
    calls = []
    result = manager(fake_client([json.dumps(GOOD)], calls)).process(RECORD)
    assert result["urgency_score"] == 7 and result["ai_status"] == "ok"
    assert result["part_name"] == "Engine Oil"  # original fields kept
    assert len(calls) == 1


def test_process_returns_one_combined_brake_urgency():
    history = [
        {"service_date": "01-01-2022", "service_odometer": 20000, "service_action": "replace"},
        {"service_date": "01-01-2024", "service_odometer": 40000, "service_action": "replace"},
        {"service_date": "01-01-2026", "service_odometer": 61000, "service_action": "replace"},
    ]
    record = {**RECORD, "part_name": "Brake Pads", "brake_pad_history": history}
    result = manager(fake_client([json.dumps(GOOD_HISTORY)], [])).process(record)
    assert result["urgency_score"] == 7
    assert result["history_pattern"] == GOOD_HISTORY["history_pattern"]
    assert "history_analysis" not in result


def test_process_retries_after_malformed_response():
    calls = []
    result = manager(fake_client(["not json", json.dumps(GOOD)], calls)).process(RECORD)
    assert result["ai_status"] == "ok"
    assert len(calls) == 2


def test_process_falls_back_after_repeated_malformed_responses():
    calls = []
    ai = manager(fake_client(['{"urgency_score": 99}'], calls), max_attempts=2)
    result = ai.process(RECORD)
    assert result["ai_status"] == "unavailable"
    assert result["urgency_score"] is None
    assert len(calls) == 2


def test_call_api_returns_none_instead_of_raising():
    # orig call_api: a failing AI gives None, never an exception.
    gemini = GeminiProvider(fake_client([TimeoutError("timed out")], []))
    assert gemini.ask("hi", None) is None
    assert AIManager([gemini], retry_delay=0).ask("hi", None) == (None, "none")


# --- The car's manual is attached to every request -------------------------------

def test_process_attaches_manual_before_prompt():
    calls = []
    result = manager(fake_client([json.dumps(GOOD)], calls)).process(
        RECORD, manual_path="manuals/kia_forte.pdf")
    assert calls[0][0] == "<uploaded manuals/kia_forte.pdf>"  # manual first
    assert "Engine Oil" in calls[0][1]                       # then the prompt
    assert result["manual_reference"] == "Maintenance schedule, p. 7"


def test_fallback_has_every_ai_field():
    calls = []
    result = manager(fake_client(["garbage"], calls)).process(RECORD)
    for key in ResponseValidator.REQUIRED_KEYS:
        assert key in result


# --- Groq backup when Gemini fails -----------------------------------------------

GROQ_ANSWER = {**GOOD, "urgency_score": 6, "manual_reference": "Schedule table (text)"}


def test_gemini_answer_is_used_and_backup_not_called():
    gemini_calls, groq_calls = [], []
    result = manager(fake_client([json.dumps(GOOD)], gemini_calls),
                     fake_groq([json.dumps(GROQ_ANSWER)], groq_calls)).process(RECORD)
    assert result["ai_provider"] == "Gemini"
    assert result["urgency_score"] == 7
    assert groq_calls == []


def test_backup_answers_when_gemini_fails():
    groq_calls = []
    result = manager(fake_client([ConnectionError("down")], []),
                     fake_groq([json.dumps(GROQ_ANSWER)], groq_calls)).process(RECORD)
    assert result["ai_provider"] == "Groq (backup)"
    assert result["urgency_score"] == 6
    assert len(groq_calls) == 1


def test_backup_works_with_no_gemini_key():
    result = manager(None, fake_groq([json.dumps(GROQ_ANSWER)], [])).process(RECORD)
    assert result["ai_provider"] == "Groq (backup)"


def test_manual_review_when_both_fail():
    result = manager(fake_client([TimeoutError("slow")], []),
                     fake_groq([ConnectionError("down")], [])).process(RECORD)
    assert result["ai_status"] == "unavailable"
    assert result["ai_provider"] == "none"


def test_backup_receives_the_manual_text(monkeypatch):
    groq_calls = []
    monkeypatch.setattr(ManualReader, "text",
                        lambda self, path: "Engine oil: replace every 7,500 km")
    manager(fake_client([ConnectionError("down")], []),
            fake_groq([json.dumps(GROQ_ANSWER)], groq_calls)).process(
        RECORD, manual_path="manuals/kia_forte.pdf")
    assert groq_calls[0].startswith("OWNER'S MANUAL")
    assert "replace every 7,500 km" in groq_calls[0]
    assert "urgency_score" in groq_calls[0]  # the normal prompt follows the manual


def one_page_pdf(text: str) -> bytes:
    """A minimal valid PDF with one line of text (no extra libraries needed)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return out


def test_manual_text_is_extracted_from_pdf():
    import os, tempfile
    path = os.path.join(tempfile.mkdtemp(), "manual.pdf")
    with open(path, "wb") as f:
        f.write(one_page_pdf("Engine oil every 10000 km or 12 months"))
    assert "Engine oil every 10000 km" in ManualReader().text(path)


def test_manual_text_of_unreadable_file_is_empty():
    import os, tempfile
    path = os.path.join(tempfile.mkdtemp(), "broken.pdf")
    with open(path, "w") as f:
        f.write("this is not a pdf")
    assert ManualReader().text(path) == ""


# --- Keeping the backup request inside Groq's free-tier limit (fixes 413) ----------

MANUAL = "\n".join([
    "SCHEDULED MAINTENANCE",
    "Item | Interval",
    "Engine oil and filter | 7,500 km or 6 months",
    "Brake pads | inspect every 15,000 km",
    "Brake fluid | replace every 30,000 km or 24 months",
    "Audio system | see chapter 4",
    "Seat adjustment | see chapter 2",
])


def test_excerpt_keeps_only_lines_about_the_part():
    excerpt = ManualReader().excerpt(MANUAL, "Brake Pads")
    assert "Brake pads | inspect every 15,000 km" in excerpt
    assert "Seat adjustment" not in excerpt


def test_excerpt_finds_parts_under_the_manuals_own_names():
    # US-style manuals say "tire" and "air cleaner", not "tyre" and "air filter".
    reader = ManualReader()
    manual = "\n".join(["Seat adjustment | see chapter 2", "",
                        "Tire rotation | every 13,000 km or 12 months", "", "Audio | chapter 4", "",
                        "Air cleaner filter | replace every 39,000 km", "", "Radio | chapter 5"])
    assert "Tire rotation" in reader.excerpt(manual, "Tyres")
    assert "Air cleaner filter" in reader.excerpt(manual, "Engine Air Filter")
    assert "Seat adjustment" not in reader.excerpt(manual, "Tyres")


def test_excerpt_is_capped():
    huge = "\n".join(f"Brake pads note {i}" for i in range(50_000))
    assert len(ManualReader().excerpt(huge, "Brake Pads")) <= ManualReader.MAX_MANUAL_CHARS


def test_backup_request_fits_free_tier_even_with_a_huge_manual(monkeypatch):
    groq_calls = []
    monkeypatch.setattr(ManualReader, "text",
                        lambda self, path: "\n".join(f"Engine oil line {i}" for i in range(100_000)))
    manager(fake_client([ConnectionError("503 UNAVAILABLE")], []),
            fake_groq([json.dumps(GROQ_ANSWER)], groq_calls)).process(
        RECORD, manual_path="manuals/kia_forte.pdf")
    approx_prompt_tokens = len(groq_calls[0]) / 4  # ~4 characters per token
    assert approx_prompt_tokens + GroqProvider.MAX_ANSWER_TOKENS < 8000


def test_brake_prompt_combines_manual_and_history_into_one_score():
    history = [{"service_action": "replace", "service_odometer": km}
               for km in (20000, 40000, 60000)]
    prompt = builder.build({**RECORD, "part_name": "Brake Pads", "brake_pad_history": history})
    assert "PERSONALISED BRAKE-PAD HISTORY" in prompt
    assert "replacement-to-replacement" in prompt
    assert "ONE combined urgency_score" in prompt
    assert "Do not create a separate history urgency score" in prompt
    assert "60000" in prompt


def test_brake_prompt_ignores_too_little_history():
    prompt = builder.build({**RECORD, "part_name": "Brake Pads",
                            "brake_pad_history": [{"service_odometer": 20000}]})
    assert "PERSONALISED BRAKE-PAD HISTORY" not in prompt
    assert "history_pattern" not in prompt


def test_brake_prompt_keeps_inspections_as_context():
    history = [
        {"service_date": "01-01-2022", "service_odometer": 20_000, "service_action": "replace"},
        {"service_date": "01-06-2022", "service_odometer": 25_000, "service_action": "inspect"},
        {"service_date": "01-01-2023", "service_odometer": 40_000, "service_action": "replace"},
        {"service_date": "01-01-2024", "service_odometer": 60_000, "service_action": "replace"},
    ]
    prompt = builder.build({**RECORD, "part_name": "Brake Pads", "brake_pad_history": history})
    assert '"service_action": "inspect"' in prompt
    assert "count ONLY service_action=replace" in prompt
    assert "replacement-to-replacement mileage intervals" in prompt


# --- OOP behaviour: abstract class, template method, polymorphism -----------------

class FakeProvider(AIProvider):
    """A test-only AIProvider subclass: returns canned replies (or raises them)."""

    def __init__(self, label, replies, client="fake-client"):
        super().__init__(client, "fake-model")
        self._label = label
        self._replies = list(replies)
        self.calls = 0

    @property
    def name(self):
        return self._label

    def _send(self, prompt, manual_path, part_name):
        self.calls += 1
        reply = self._replies[min(self.calls, len(self._replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_ai_provider_is_abstract():
    try:
        AIProvider(client=object())
    except TypeError:
        return
    raise AssertionError("AIProvider should not be instantiable")


def test_manager_works_with_any_provider_subclass():
    # Polymorphism: AIManager only calls provider.ask(); the subclass doesn't matter.
    custom = FakeProvider("Custom AI", [json.dumps(GOOD)])
    result = AIManager([custom], retry_delay=0).process(RECORD)
    assert result["ai_provider"] == "Custom AI"
    assert result["urgency_score"] == 7
    assert custom.calls == 1


def test_providers_are_tried_in_list_order_until_one_replies():
    first = FakeProvider("First", [None])
    second = FakeProvider("Second", [json.dumps(GOOD)])
    third = FakeProvider("Third", [json.dumps(GROQ_ANSWER)])
    reply, who = AIManager([first, second, third], retry_delay=0).ask("hi", None)
    assert who == "Second" and json.loads(reply) == GOOD
    assert (first.calls, second.calls, third.calls) == (1, 1, 0)
    # Changing the list order changes who answers first.
    reply, who = AIManager([third, second], retry_delay=0).ask("hi", None)
    assert who == "Third"


def test_provider_ask_swallows_errors_from_send():
    # Template method: ask() turns any exception raised by _send() into None.
    broken = FakeProvider("Broken", [RuntimeError("boom")])
    assert broken.ask("hi", None) is None
    assert broken.calls == 1


def test_unavailable_provider_is_skipped_without_calling_send():
    no_key = FakeProvider("No key", [json.dumps(GOOD)], client=None)
    backup = FakeProvider("Backup", [json.dumps(GROQ_ANSWER)])
    assert not no_key.is_available and backup.is_available
    assert no_key.ask("hi", None) is None and no_key.calls == 0
    result = AIManager([no_key, backup], retry_delay=0).process(RECORD)
    assert result["ai_provider"] == "Backup"
    assert no_key.calls == 0
    assert GeminiProvider(None).is_available is False
    assert GroqProvider(fake_groq([], [])).is_available is True


# --- AIProviderFactory (Factory pattern) and specific errors --------------------

def test_factory_creates_each_provider_type():
    from ai.ai_provider_factory import AIProviderFactory

    gemini = AIProviderFactory.create("gemini", None, timeout_seconds=60)
    groq = AIProviderFactory.create("groq", None, timeout_seconds=60)
    assert isinstance(gemini, GeminiProvider) and isinstance(groq, GroqProvider)
    # No API key: the provider exists but is not available, so it is skipped.
    assert not gemini.is_available and not groq.is_available


def test_factory_rejects_an_unknown_provider():
    from ai.ai_provider_factory import AIProviderFactory

    try:
        AIProviderFactory.create("chatbot9000", "key", timeout_seconds=60)
    except ValueError:
        return
    raise AssertionError("an unknown provider name should raise ValueError")


def test_gemini_api_error_is_caught_and_backup_answers():
    from google.genai import errors as genai_errors

    calls_g, calls_q = [], []
    ai = manager(fake_client([genai_errors.APIError("503 busy")], calls_g),
                 fake_groq([json.dumps(GOOD)], calls_q))
    result = ai.process(RECORD)
    assert result["ai_status"] == "ok" and result["ai_provider"] == "Groq (backup)"
