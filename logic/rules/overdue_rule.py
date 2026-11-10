"""
Routing rule: overdue by the manufacturer's schedule.
"""
from __future__ import annotations

from logic.rules.outcome_rule import OutcomeRule


class OverdueRule(OutcomeRule):
    """Overdue by the manufacturer's schedule (km or time) -> DUE SOON."""

    def outcome(self, record: dict, facts: dict) -> str | None:
        if facts["is_overdue"]:
            return "DUE SOON - Overdue by manufacturer schedule"
        return None
