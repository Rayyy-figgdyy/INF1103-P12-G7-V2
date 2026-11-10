"""
Routing rule: a non-critical service can wait if the COE ends soon.
"""
from __future__ import annotations

from logic.rules.outcome_rule import OutcomeRule


class CoeDeferRule(OutcomeRule):
    """COE defer rule: COE ends within 180 days AND not a safety part AND urgency 4 or
    less -> the service can wait (the car may soon be off the road)."""

    COE_DEFER_WINDOW_DAYS = 180      # "COE ends soon" = within 180 days (about 6 months)
    MAX_URGENCY = 4

    def outcome(self, record: dict, facts: dict) -> str | None:
        coe_days_left = facts["coe_days_left"]
        coe_ends_soon = coe_days_left is not None and coe_days_left <= self.COE_DEFER_WINDOW_DAYS
        if (coe_ends_soon and not facts["is_safety_critical"]
                and record.get("urgency_score") <= self.MAX_URGENCY):
            return "DEFER - COE expires soon, non-critical service can wait"
        return None
