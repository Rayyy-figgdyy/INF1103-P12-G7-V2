"""
Routing rule: the catch-all last rule.
"""
from __future__ import annotations

from logic.rules.outcome_rule import OutcomeRule


class MonitorRule(OutcomeRule):
    """The last rule: always applies, so every check gets an outcome (urgency 4-7)."""

    OUTCOME = "MONITOR - Service approaching"

    def outcome(self, record: dict, facts: dict) -> str | None:
        return self.OUTCOME
