"""
Menu options 5-6: AI urgency checks and the urgent list.
"""
from __future__ import annotations

import datetime

from controllers.check_record_builder import CheckRecordBuilder
from controllers.history_controller import HistoryController
from controllers.maintenance_pipeline import MaintenancePipeline
from data_manager import DataManager
from io_manager import IOManager
from logic.brake_history_analyser import BrakeHistoryAnalyser
from logic.history_rules import HistoryRules
from logic_manager import LogicManager
from models.user_profile import UserProfile


class CheckController:
    """AI urgency checks (menu option 5) and the urgent list (menu option 6).
    AGGREGATION: the managers, the pipeline and the HistoryController are passed in.
    ASSOCIATION: each method uses the UserProfile it is handed, without keeping it."""

    def __init__(self, io: IOManager, data: DataManager, logic: LogicManager,
                 rules: HistoryRules, brake_analyser: BrakeHistoryAnalyser,
                 pipeline: MaintenancePipeline, history: HistoryController):
        self.__io = io
        self.__data = data
        self.__logic = logic
        self.__rules = rules
        self.__pipeline = pipeline
        self.__history = history         # used when a part has no history yet
        # COMPOSITION: the record builder is created here and owned by this controller.
        self.__record_builder = CheckRecordBuilder(data, brake_analyser)        # used when a part has no history yet

    def __check_setup(self, user: UserProfile) -> tuple | None:
        """Ask which part to check. Returns (manual path, part, stored rule) or None."""
        car_model = user.car_model
        manual_path = self.__data.cars.get_manual_path(car_model)
        if manual_path is None:
            self.__io.display_message(f"The manual for {car_model} is missing, so parts can't be checked.")
            return None
        # Business rule 2: parts and intervals come from cars.json, never from the AI.
        parts = self.__data.cars.list_parts(car_model)
        if not parts:
            self.__io.display_message("No service schedule is available, so parts can't be checked.")
            return None
        part_name = self.__io.prompt_part_choice(parts)
        interval = self.__data.cars.get_service_interval(car_model, part_name)
        if interval is None:
            self.__io.display_message(f"No stored service interval for {part_name}.")
            return None
        return manual_path, part_name, interval

    def __latest_service_for_check(self, user: UserProfile, part_name: str,
                                  interval: dict) -> tuple:
        """The latest service that resets this part's interval (an inspection doesn't
        reset a replacement interval)."""
        history = self.__data.history.for_plate(user.license_plate)
        model_year = self.__history.earliest_service_date(user)
        model_year = None if model_year is None else model_year.year
        last_service = self.__rules.latest_service(history, part_name,
                                                  interval.get("action", "replace"), model_year)
        return history, model_year, last_service

    def confirm_legacy_action(self, user: UserProfile, part_name: str,
                              history: list[dict]) -> bool:
        """Ask the owner what was actually performed in one old maintenance record.
        Legacy entries remain unchanged until the user explicitly confirms an action."""
        unknown = [
            entry for entry in history
            if entry.get("part_name") == part_name
            and entry.get("service_action") in (None, "unknown")
        ]
        if not unknown:
            return False

        self.__io.display_message(
            "\nSome older services have no recorded action (inspect/replace/rotate). "
            "Please confirm one using your workshop record."
        )
        if not self.__io.confirm_action("Confirm an older service action now?"):
            return False

        # Reuse the existing service-selection and action menus (IO stays in IOManager).
        selected = self.__io.prompt_service_choice(unknown, "confirm")
        if selected is None:
            return False
        action = self.__io.prompt_service_action(part_name)
        updated = dict(selected)
        updated["service_action"] = action
        if not self.__data.history.update(updated):
            self.__io.display_message("Could not save the confirmed action.")
            return False
        self.__io.display_message("Old maintenance action confirmed and saved.")
        return True

    def __resolve_last_service(self, user: UserProfile, part_name: str,
                              interval: dict) -> tuple | None:
        """A usable last service, asking the owner to add one when needed.
        Returns (last_service, history, model_year, from_new) or None."""
        history, model_year, last_service = self.__latest_service_for_check(user, part_name, interval)
        from_new = False
        if last_service is not None:
            return last_service, history, model_year, from_new

        # An older history entry may be present but have no confirmed service action.
        # Allow the owner to correct that entry rather than discarding their history.
        if self.confirm_legacy_action(user, part_name, history):
            history, model_year, last_service = self.__latest_service_for_check(
                user, part_name, interval)
            if last_service is not None:
                return last_service, history, model_year, from_new

        self.__io.display_message(
            f"\nThere is no confirmed {part_name} service that resets this interval yet.")
        # A 'first at X, then every Y' part may never have been replaced: count from new.
        if "repeat_km" in interval and model_year is not None:
            from_new = not self.__io.confirm_action(f"Has the {part_name} ever been replaced?")
        if from_new:
            last_service = self.__rules.from_new_service(part_name, model_year)
            return last_service, history, model_year, from_new

        if not self.__io.confirm_action(f"Add your last {part_name} service now?"):
            return None
        if not self.__history.add_services(user, part_name):
            return None
        history, model_year, last_service = self.__latest_service_for_check(user, part_name, interval)
        if last_service is None:
            self.__io.display_message(
                "The entry was saved, but an inspection does not reset this service interval. "
                "Record the last replacement or rotation before checking this part.")
            return None
        return last_service, history, model_year, from_new

    def __display_check_service(self, part_name: str, last_service: dict, from_new: bool) -> None:
        if from_new:
            self.__io.display_message(f"\nChecking your {part_name} from new "
                                     "(the manual's first-change interval applies):")
        else:
            self.__io.display_message(f"\nUsing your last {part_name} service from your history:")
        self.__io.display_service(last_service)

    def __prompt_check_odometer(self, user: UserProfile, last_service: dict,
                               history: list[dict]) -> int:
        """Ask for today's odometer within the rule-1 and km-per-day limits."""
        plate = user.license_plate
        latest_reading = self.__rules.latest_reading(history, self.__data.checks.for_plate(plate))
        max_plausible = None
        if latest_reading is not None:
            reading_date, reading_odometer = latest_reading
            max_plausible = self.__rules.max_plausible_odometer(
                reading_date, reading_odometer, datetime.date.today())
        return self.__io.prompt_current_odometer(
            last_service["service_odometer"], self.__data.last_odometer_on_file(plate),
            max_plausible)

    def build_check_record(self, user: UserProfile, part_name: str, last_service: dict,
                           current_odometer: int, chosen_interval: dict,
                           model_year: int | None) -> dict:
        """The record sent to the AI (built by CheckRecordBuilder, shared with the GUI)."""
        return self.__record_builder.build(user, part_name, last_service, current_odometer,
                                           chosen_interval, model_year)

    def check_part(self, user: UserProfile) -> UserProfile:
        """Menu option 5: assess one part using the manual, history and current mileage."""
        setup = self.__check_setup(user)
        if setup is None:
            return user
        manual_path, part_name, interval = setup

        service_details = self.__resolve_last_service(user, part_name, interval)
        if service_details is None:
            return user
        last_service, history, model_year, from_new = service_details
        self.__display_check_service(part_name, last_service, from_new)

        # The interval may change after the part's first replacement.
        part_services = [s for s in history if s.get("part_name") == part_name]
        chosen_interval = self.__rules.choose_interval(interval, part_services)
        current_odometer = self.__prompt_check_odometer(user, last_service, history)
        raw_record = self.build_check_record(user, part_name, last_service, current_odometer,
                                             chosen_interval, model_year)

        # Same inputs as a saved check: show it again instead of calling the AI (C4).
        previous = self.__data.checks.find_repeat(raw_record)
        if previous is not None:
            self.__io.display_repeated(previous)
            return user

        self.__io.display_message("\nAsking the AI to check this part against your manual...")
        final_record = self.__pipeline.assess(raw_record, manual_path)
        if not self.__data.checks.save(final_record):
            self.__io.display_message("Warning: the assessment could not be saved to disk.")
        self.__io.display_result(final_record)
        return user

    def urgent(self, user: UserProfile) -> UserProfile:
        """Menu option 6: each part's latest assessment that needs attention."""
        saved_checks = self.__data.checks.for_plate(user.license_plate)
        # New relevant servicing makes a previous warning outdated, even if no fresh
        # AI check has been run yet. Keep the old check in JSON history for reference.
        history = self.__data.history.for_plate(user.license_plate)
        urgent_records = []
        for record in self.__rules.latest_check_per_part(saved_checks):
            if self.__rules.is_check_superseded(record, history):
                continue  # The user must run a new check after servicing.
            if self.__logic.is_urgent(record):
                urgent_records.append(record)
        urgent_records.sort(key=lambda record: record.get("risk_score", 0), reverse=True)
        if not urgent_records:
            self.__io.display_message(
                "\nNothing needs attention right now: none of your parts' latest "
                "checks are urgent, flagged, overdue or waiting for manual review. "
                "(Choose 2 to see your history.)")
            return user
        self.__io.display_list(urgent_records)
        return user
