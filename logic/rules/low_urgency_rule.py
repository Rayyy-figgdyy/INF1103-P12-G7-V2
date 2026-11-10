"""
Routing rule: low AI urgency means OK.
"""
from __future__ import annotations

from logic.rules.outcome_rule import OutcomeRule


class LowUrgencyRule(OutcomeRule):
    """AI urgency 1-3 and nothing above applied -> OK."""

    MAX_URGENCY = 3

    def outcome(self, record: dict, facts: dict) -> str | None:
        if record.get("urgency_score") <= self.MAX_URGENCY:
            return "OK - Not urgent"
        return None
