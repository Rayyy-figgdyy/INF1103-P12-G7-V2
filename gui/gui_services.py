"""
GuiServices: the managers and services every GUI page shares. Streamlit re-runs the
script after each click, so StreamlitGui keeps one GuiServices per browser session.
"""
from __future__ import annotations

from ai.fuel_ai_manager import FuelAIManager
from controllers.check_record_builder import CheckRecordBuilder
from controllers.maintenance_pipeline import MaintenancePipeline
from logic.brake_history_analyser import BrakeHistoryAnalyser
from logic.fuel_logic_manager import FuelLogicManager
from logic.history_rules import HistoryRules
from services.fuel_service import FuelService
from storage.fuel_data_manager import FuelDataManager


class GuiServices:
    """AGGREGATION: the three managers can be passed in (the tests pass fakes);
    otherwise the real ones are built. COMPOSITION: the rules, pipeline, record
    builder and fuel service are created here and live as long as this object."""

    def __init__(self, data: FuelDataManager | None = None, ai: FuelAIManager | None = None,
                 logic: FuelLogicManager | None = None):
        self.__data = data or FuelDataManager()
        self.__ai = ai or FuelAIManager.from_env()
        self.__logic = logic or FuelLogicManager()
        self.__rules = HistoryRules()
        self.__pipeline = MaintenancePipeline(self.__ai, self.__logic)
        self.__record_builder = CheckRecordBuilder(self.__data,
                                                   BrakeHistoryAnalyser(self.__rules))
        self.__fuel = FuelService(self.__data.fuel, self.__data.fuel_assessments,
                                  maintenance_history=self.__data.history,
                                  maintenance_rules=self.__rules,
                                  reviews=self.__data.fuel_reviews)

    @property
    def data(self) -> FuelDataManager:
        return self.__data

    @property
    def ai(self) -> FuelAIManager:
        return self.__ai

    @property
    def logic(self) -> FuelLogicManager:
        return self.__logic

    @property
    def rules(self) -> HistoryRules:
        return self.__rules

    @property
    def pipeline(self) -> MaintenancePipeline:
        return self.__pipeline

    @property
    def record_builder(self) -> CheckRecordBuilder:
        return self.__record_builder

    @property
    def fuel(self) -> FuelService:
        return self.__fuel