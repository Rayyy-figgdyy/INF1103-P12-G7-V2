# Keep the original maintenance rules and add AI-driven fuel follow-up decisions.
from __future__ import annotations

from logic_manager import LogicManager
from logic.fuel_follow_up_rules import FuelFollowUpRules


class FuelLogicManager(LogicManager):

    # Use validated AI fields; measured percentages do not determine the anomaly category.
    def evaluate_fuel(self, dashboard: dict, ai_result: dict) -> dict:
        return FuelFollowUpRules().decide(dashboard, ai_result)
