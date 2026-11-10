"""
Routing rule: overdue brake pads or tyres are always urgent.
"""
from __future__ import annotations

from logic.rules.outcome_rule import OutcomeRule


class SafetyOverdueRule(OutcomeRule):
    """Safety net: overdue brake pads or tyres are ALWAYS urgent, even if the AI's
    urgency is low. The wording follows the manual's action, so an overdue brake
    INSPECTION isn't reported as if the pads themselves must be replaced."""

    # What each stored action is called in the outcome text.
    OVERDUE_WORDING = {"replace": "part", "inspect": "inspection", "rotate": "tyre rotation"}

    def outcome(self, record: dict, facts: dict) -> str | None:
        if facts["is_safety_critical"] and facts["is_overdue"]:
            what = self.OVERDUE_WORDING.get(record.get("action"), "part")
            return f"URGENT - Safety-critical {what} overdue"
        return None
