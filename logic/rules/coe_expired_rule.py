"""
Routing rule: an expired COE comes first.
"""
from __future__ import annotations

from logic.rules.outcome_rule import OutcomeRule


class CoeExpiredRule(OutcomeRule):
    """Singapore: an expired COE means the car can't legally be driven, so servicing
    advice is pointless until the COE is renewed."""

    def outcome(self, record: dict, facts: dict) -> str | None:
        coe_days_left = facts["coe_days_left"]
        if coe_days_left is not None and coe_days_left < 0:
            return "COE EXPIRED - Renew the COE or deregister before servicing"
        return None
