# Coordinate validated fuel measurements, saved AI assessments and whole-period reviews.
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from ai.fuel_ai_advisor import FuelAIAdvisor
from models.fuel_entry import FuelEntry
from logic.fuel_efficiency_analyser import FuelEfficiencyAnalyser
from logic.fuel_alert_tracker import FuelAlertTracker
from storage.fuel_repository import FuelRepository
from storage.fuel_assessment_repository import FuelAssessmentRepository
from storage.fuel_review_repository import FuelReviewRepository


class FuelService:
    ANALYSIS_VERSION = "fuel-ai-anomaly-assessment-v3"

    # The service owns the alert tracker while reusing the supplied repositories.
    def __init__(self, repository: FuelRepository,
                 assessments: FuelAssessmentRepository | None = None,
                 analyser: FuelEfficiencyAnalyser | None = None,
                 maintenance_history=None, maintenance_rules=None,
                 reviews: FuelReviewRepository | None = None):
        self.__repository = repository
        self.__assessments = assessments
        self.__analyser = analyser or FuelEfficiencyAnalyser()
        self.__alerts = FuelAlertTracker()
        self.__maintenance_history = maintenance_history
        self.__maintenance_rules = maintenance_rules
        self.__reviews = reviews
        if maintenance_history is not None and maintenance_rules is None:
            raise ValueError("Maintenance validation rules are required.")

    # Dates and odometers must still agree after an edit moves a record.
    @staticmethod
    def __check_order(entries: list[FuelEntry]) -> None:
        ordered = sorted(entries, key=lambda item: item.odometer_km)
        for earlier, later in zip(ordered, ordered[1:]):
            if earlier.odometer_km >= later.odometer_km:
                raise ValueError("Two refuels cannot have the same odometer reading.")
            earlier_date = datetime.strptime(earlier.refuel_date, FuelEntry.DATE_FORMAT)
            later_date = datetime.strptime(later.refuel_date, FuelEntry.DATE_FORMAT)
            if later_date < earlier_date:
                raise ValueError("Refuel dates and odometer readings must be in order.")

    # Reuse the original maintenance validation for this vehicle.
    def __check_maintenance(self, entry: FuelEntry) -> None:
        if self.__maintenance_history is None:
            return
        history = self.__maintenance_history.for_plate(entry.license_plate)
        problem = self.__maintenance_rules.check_service_odometer(
            history, entry.refuel_date, entry.odometer_km)
        if not problem:
            problem = self.__maintenance_rules.check_service_pace(
                history, entry.refuel_date, entry.odometer_km, None)
        if problem:
            raise ValueError("Fuel record does not match maintenance history: " + problem)

    # Saving raw measurements does not call AI or classify a fuel anomaly.
    def add_refuel(self, license_plate: str, refuel_date: str, odometer_km: int,
                   litres: float) -> FuelEntry:
        entry = FuelEntry(license_plate, refuel_date, odometer_km, litres)
        history = self.get_history(entry.license_plate)
        if history and entry.odometer_km <= history[-1].odometer_km:
            raise ValueError("New odometer must be higher than the last fuel reading.")
        self.__check_order(history + [entry])
        self.__check_maintenance(entry)
        saved = self.__repository.add(entry)
        if saved is None:
            raise OSError("Could not save the fuel record.")
        return saved

    # Keep each vehicle's measurements separate.
    def get_history(self, license_plate: str) -> list[FuelEntry]:
        return self.__repository.for_plate(license_plate)

    # Validate the entire sequence before replacing an entry.
    def update_refuel(self, license_plate: str, entry_id: int, refuel_date: str,
                      odometer_km: int, litres: float) -> FuelEntry:
        history = self.get_history(license_plate)
        old = next((entry for entry in history if entry.entry_id == entry_id), None)
        if old is None:
            raise ValueError("Fuel record was not found.")
        changed = FuelEntry(license_plate, refuel_date, odometer_km, litres,
                            entry_id=entry_id, segment_start=old.segment_start)
        self.__check_order([entry for entry in history if entry.entry_id != entry_id] + [changed])
        self.__check_maintenance(changed)
        if not self.__repository.update(changed):
            raise OSError("Could not update the fuel record.")
        return changed

    # A deleted measurement breaks continuity rather than creating a guessed interval.
    def delete_refuel(self, license_plate: str, entry_id: int) -> bool:
        return self.__repository.delete(license_plate, entry_id)

    # Bind an assessment or review to the exact source measurements.
    @staticmethod
    def history_key(history: list[FuelEntry]) -> str:
        raw = json.dumps([entry.to_dict() for entry in history], sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # Later refuels preserve valid reviews; editing their source records invalidates them.
    def __valid_reviews(self, license_plate: str, history: list[FuelEntry]) -> tuple[list[dict], int]:
        if self.__reviews is None:
            return [], 0
        valid = []
        ignored = 0
        for review in self.__reviews.for_plate(license_plate):
            position = next((index for index, entry in enumerate(history)
                             if entry.entry_id == review["through_entry_id"]), None)
            if position is not None and self.history_key(history[:position + 1]) == review["history_key"]:
                valid.append(review)
            else:
                ignored += 1
        return valid, ignored

    # Old numerical-warning reports cannot create alerts under the new AI contract.
    def __valid_assessments(self, license_plate: str, history: list[FuelEntry]) -> list[dict]:
        if self.__assessments is None:
            return []
        valid = []
        by_id = {point["entry_id"]: point for point in self.__analyser.measure(history)}
        for record in self.__assessments.for_plate(license_plate):
            result = record.get("result")
            if (not isinstance(result, dict) or result.get("ai_status") != "ok"
                    or result.get("analysis_version") != self.ANALYSIS_VERSION
                    or FuelAIAdvisor.validate_result(result) is None):
                continue
            through_id = result.get("assessed_through_entry_id")
            if isinstance(through_id, bool) or not isinstance(through_id, int) or through_id not in by_id:
                continue
            through = by_id[through_id]
            reference = result.get("comparison_reference")
            if not self.__alerts.valid_reference(reference, by_id):
                continue
            if any(by_id[entry_id]["position"] >= through["position"] - 2
                   for entry_id in reference["entry_ids"]):
                continue
            if any(entry_id not in by_id or by_id[entry_id]["segment"] != through["segment"]
                   or not through["position"] - 2 <= by_id[entry_id]["position"] <= through["position"]
                   for entry_id in result["flagged_entry_ids"]):
                continue
            position = next((index for index, entry in enumerate(history)
                             if entry.entry_id == through_id), None)
            if (position is not None and result.get("assessment_history_key")
                    == self.history_key(history[:position + 1])
                    and result.get("assessed_date") == history[position].refuel_date
                    and isinstance(result.get("car_model"), str)
                    and isinstance(result.get("assessment_context_key"), str)
                    and len(result["assessment_context_key"]) == 64
                    and all(letter in "0123456789abcdef" for letter in result["assessment_context_key"])):
                valid.append(dict(result))
        return valid

    # Send maintenance facts without names, licence plates or free-text notes.
    def __maintenance_context(self, license_plate: str) -> list[dict]:
        if self.__maintenance_history is None:
            return []
        fields = ("part_name", "service_date", "service_odometer", "service_action")
        return [{key: record[key] for key in fields if key in record}
                for record in self.__maintenance_history.for_plate(license_plate)
                if isinstance(record, dict)]

    # Only input changes invalidate reuse; opening the saved assessment's alert does not.
    @classmethod
    def context_key(cls, dashboard: dict) -> str:
        relevant = {"version": cls.ANALYSIS_VERSION, "history": dashboard["refuel_history"],
                    "reviews": dashboard["reviews"], "maintenance_history": dashboard["maintenance_history"],
                    "reference_percentages": dashboard["thresholds"]}
        return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode("utf-8")).hexdigest()

    # The selected car model is also part of the report-reuse check.
    @classmethod
    def data_key(cls, dashboard: dict, car_model: str) -> str:
        raw = json.dumps({"context": cls.context_key(dashboard), "car_model": car_model}, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # Restore saved AI decisions, then calculate measurements without making new decisions.
    def get_dashboard(self, license_plate: str, car_model: str | None = None) -> dict:
        history = self.get_history(license_plate)
        reviews, ignored = self.__valid_reviews(license_plate, history)
        assessments = self.__valid_assessments(license_plate, history)
        points = self.__analyser.measure(history)
        state = self.__alerts.restore(points, reviews, assessments)
        dashboard = self.__analyser.summarise(points, len(history), state)
        dashboard.update({"refuel_history": [entry.to_dict() for entry in history],
                          "reviews": reviews, "ignored_review_count": ignored,
                          "maintenance_history": self.__maintenance_context(license_plate),
                          "assessment_events": assessments})
        latest = dashboard["latest_ai_assessment"]
        dashboard["assessment_pending"] = (latest is None
            or latest.get("assessment_context_key") != self.context_key(dashboard)
            or (car_model is not None and latest.get("car_model") != car_model))
        return dashboard

    # A user reviews the whole AI-opened period; original measurements are retained.
    def review_alert(self, license_plate: str, decision: str) -> dict:
        if decision not in FuelReviewRepository.DECISIONS:
            raise ValueError("Choose ordinary variation, confirmed fault or changed conditions.")
        if self.__reviews is None:
            raise ValueError("Fuel review storage is unavailable.")
        dashboard = self.get_dashboard(license_plate)
        alert = dashboard["alert"]
        if alert is None:
            raise ValueError("There is no open fuel alert to review.")
        history = self.get_history(license_plate)
        position = next(index for index, entry in enumerate(history)
                        if entry.entry_id == alert["through_entry_id"])
        review = {"license_plate": license_plate.strip().upper(), "decision": decision,
                  "first_entry_id": alert["first_entry_id"], "through_entry_id": alert["through_entry_id"],
                  "history_key": self.history_key(history[:position + 1])}
        if not self.__reviews.save(review):
            raise OSError("Could not save the review. The alert remains open.")
        return self.get_dashboard(license_plate)

    # Validate, reuse a matching saved assessment, or request one new AI assessment.
    def analyse_with_ai(self, license_plate: str, ai_manager,
                        car_model: str, logic_manager, before_request=None) -> dict:
        dashboard = self.get_dashboard(license_plate, car_model)
        if dashboard["analysis_problem"]:
            return {"ai_status": "insufficient_history", "ai_provider": "none",
                    "message": dashboard["analysis_problem"], "saved": False, "reused": False}
        if self.__assessments is None:
            raise ValueError("Fuel assessment storage was not provided.")
        key = self.data_key(dashboard, car_model)
        history = self.get_history(license_plate)
        history_key = self.history_key(history)
        cached = self.__assessments.find_repeat(license_plate, key)
        if (cached is not None and cached.get("analysis_version") == self.ANALYSIS_VERSION
                and cached.get("assessment_history_key") == history_key
                and cached.get("assessment_context_key") == self.context_key(dashboard)
                and cached.get("car_model") == car_model
                and cached in dashboard["assessment_events"]
                and FuelAIAdvisor.validate_result(cached, dashboard) is not None):
            return {**cached, "reused": True}
        if before_request is not None:
            before_request()
        try:
            raw = ai_manager.analyse_fuel(dashboard, car_model)
        except (OSError, ValueError, RuntimeError, TypeError):
            raw = None
        valid = FuelAIAdvisor.validate_result(raw, dashboard) if isinstance(raw, dict) and raw.get("ai_status") == "ok" else None
        if valid is None:
            unavailable = {"ai_status": "unavailable", "ai_provider": "none",
                           "message": "AI could not complete a valid fuel assessment. Measurements remain available."}
            return {**unavailable, **logic_manager.evaluate_fuel(dashboard, unavailable),
                    "saved": False, "reused": False}
        result = {**valid, "ai_status": "ok", "ai_provider": raw.get("ai_provider", "AI"),
                  "analysis_version": self.ANALYSIS_VERSION, "car_model": car_model,
                  "assessment_history_key": history_key,
                  "assessment_context_key": self.context_key(dashboard),
                  "assessed_through_entry_id": history[-1].entry_id,
                  "assessed_date": history[-1].refuel_date,
                  "comparison_reference": dashboard["comparison_reference"],
                  "reused": False, "saved": True}
        points = self.__analyser.measure(history)
        state = self.__alerts.restore(points, dashboard["reviews"], dashboard["assessment_events"] + [result])
        assessed = {**dashboard, **self.__analyser.summarise(points, len(history), state)}
        result.update(logic_manager.evaluate_fuel(assessed, result))
        try:
            result["saved"] = self.__assessments.save(license_plate, key, result)
        except OSError:
            result["saved"] = False
        if not result["saved"]:
            result.update(logic_manager.evaluate_fuel(dashboard, result))
            result["message"] = "AI replied, but the report and any new alert could not be saved. Try again."
        return result
