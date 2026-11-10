"""
Runs one check through the AI first, then the business rules (C2).
"""
from __future__ import annotations

from ai_manager import AIManager
from logic_manager import LogicManager


class MaintenancePipeline:
    """Runs one maintenance check through the AI, then through the business rules.
    AGGREGATION: it is given the AIManager and LogicManager."""

    def __init__(self, ai: AIManager, logic: LogicManager):
        self.__ai = ai
        self.__logic = logic

    def assess(self, raw_record: dict, manual_path: str | None = None) -> dict:
        """Constraint C2: every check passes through the AI. Returns the finished record
        with the AI fields, the calculated facts, the risk score and the outcome."""
        # The AI combines the manual and any eligible Brake Pad history into one score.
        final_record = dict(self.__ai.process(raw_record, manual_path=manual_path))
        # Then the deterministic rules: facts, risk score (sorting only) and outcome.
        final_record.update(self.__logic.evaluate(final_record))
        final_record["risk_score"] = self.__logic.score(final_record)
        final_record["outcome"] = self.__logic.route(final_record)
        return final_record
