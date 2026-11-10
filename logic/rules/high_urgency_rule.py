"""
Routing rule: the multi-condition rule (AI urgency AND AI confidence).
"""
from __future__ import annotations

from logic.rules.outcome_rule import OutcomeRule


class HighUrgencyRule(OutcomeRule):
    """MULTI-CONDITION RULE (required by the brief): combines the AI's urgency AND its
    confidence. A high score is only acted on directly when the AI is sure; otherwise
    a mechanic should confirm it."""

    HIGH_URGENCY = 8

    def outcome(self, record: dict, facts: dict) -> str | None:
        urgency = record.get("urgency_score")
        if urgency >= self.HIGH_URGENCY and record.get("confidence") == "High":
            return "URGENT - Service immediately"
        if urgency >= self.HIGH_URGENCY:
            return "FLAGGED - High urgency but low AI confidence, verify with a mechanic"
        return None
