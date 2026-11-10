"""
AI pipeline steps 3-4: parse the AI's reply and validate it against the JSON
schema (C3) before any field is used.
"""
from __future__ import annotations

import json
import logging

# Logged under the AI Manager's name, so its messages read "ai_manager: ...".
logger = logging.getLogger("ai_manager")


class ResponseValidator:
    """Steps 3-4: read the JSON object out of the AI's reply and check it (C3)."""

    # C3: the JSON schema every AI answer must match.
    REQUIRED_KEYS = ("urgency_score", "confidence", "overdue_summary",
                     "recommended_action", "manual_reference")
    VALID_CONFIDENCE = ("High", "Medium", "Low")

    def parse(self, reply: str | None) -> dict | None:
        """Extract the JSON object from the AI's reply text.
        Returns it as a dictionary, or None if there is no readable JSON object."""
        if not reply or not reply.strip():
            return None
        # Take text from the first { to the last }
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

    def validate(self, data: dict | None, expect_history: bool = False) -> dict | None:
        """Validate one combined AI assessment before the rest of the app uses it.
        Returns a clean answer dict (with ai_status "ok"), or None if anything is wrong."""
        if not isinstance(data, dict):
            return None

        for key in self.REQUIRED_KEYS:
            if key not in data:
                logger.error("AI response is missing %r: %s", key, data)
                return None

        # Urgency_score must be an int 1-10, whole number float is accepted
        score = data["urgency_score"]
        if isinstance(score, float) and score.is_integer():
            score = int(score)
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 10:
            logger.error("AI response has an invalid urgency_score: %r", data["urgency_score"])
            return None

        if data["confidence"] not in self.VALID_CONFIDENCE:
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

        # Eligible Brake Pad history is part of the same assessment, not a second different score
        if expect_history:
            pattern = data.get("history_pattern")
            if not isinstance(pattern, str) or not pattern.strip():
                logger.error("AI response is missing a valid brake history_pattern: %r", pattern)
                return None
            answer["history_pattern"] = pattern.strip()

        return answer
