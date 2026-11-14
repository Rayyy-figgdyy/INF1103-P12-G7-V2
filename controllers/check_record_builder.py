"""
CheckRecordBuilder: builds the record an AI urgency check sends to the AI. Used by
the terminal CheckController and by the GUI's CheckPage, so both send the same data.
"""
from __future__ import annotations

import datetime

from data_manager import DataManager
from logic.brake_history_analyser import BrakeHistoryAnalyser
from models.user_profile import UserProfile


class CheckRecordBuilder:
    """SRP: building the check record is its only job.
    AGGREGATION: it is given the DataManager and the BrakeHistoryAnalyser."""

    def __init__(self, data: DataManager, brake_analyser: BrakeHistoryAnalyser):
        self.__data = data
        self.__brake_analyser = brake_analyser

    def build(self, user: UserProfile, part_name: str, last_service: dict,
              current_odometer: int, chosen_interval: dict,
              model_year: int | None) -> dict:
        """The record sent to the AI; brake pads also carry their validated history."""
        today = datetime.date.today()
        raw_record = {
            "license_plate": user.license_plate,
            "car_model": user.car_model,
            "car_condition": user.car_condition,
            "coe_expiry_date": user.coe_expiry_date,
            "part_name": part_name,
            "check_date": today.strftime("%d-%m-%Y"),
            "service_id": last_service.get("service_id"),   # None for a "from new" check
            "last_service_date": last_service["service_date"],
            "last_service_mileage": last_service["service_odometer"],
            "last_service_action": last_service.get("service_action") or "unknown",
            "current_odometer": current_odometer,
        }
        raw_record.update(chosen_interval)

        if part_name == "Brake Pads":
            brake_history = self.__data.history.for_part(user.license_plate, part_name)
            context = self.__brake_analyser.context(brake_history, model_year, today,
                                                    current_odometer)
            raw_record["history_context"] = {
                "eligible": context["eligible"],
                "replacement_count": context["replacement_count"],
                "reason": context["reason"],
            }
            # The history is only sent once it has passed validation.
            if context["eligible"]:
                raw_record["brake_pad_history"] = brake_history
        return raw_record