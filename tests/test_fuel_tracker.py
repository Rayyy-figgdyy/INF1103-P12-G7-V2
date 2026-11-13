# These tests use made-up records, temporary files and fake AI replies.
# They never send a live API request or write to your real fuel history.
# We check how our tracker handles AI replies, not the AI provider's diagnostic accuracy.
# pytest supplies tmp_path as a separate folder for each test.
# monkeypatch supplies prepared input answers; capsys captures the printed output.
# parametrize runs the same check for each listed example, including bad inputs.
import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from ai.fuel_ai_advisor import FuelAIAdvisor
from ai.fuel_ai_manager import FuelAIManager
from ai_manager import AIManager
from controllers.fuel_controller import FuelController
from data_manager import DataManager
from fuel_io_manager import FuelIOManager
from io_manager import IOManager
from logic.fuel_efficiency_analyser import FuelEfficiencyAnalyser
from logic.fuel_logic_manager import FuelLogicManager
from logic.history_rules import HistoryRules
from logic_manager import LogicManager
from main import App
from models.fuel_entry import FuelEntry
from models.user_profile import UserProfile
from services.fuel_service import FuelService
from storage.fuel_data_manager import FuelDataManager

PLATE = "SBA1234A"
CAR_MODEL = "Honda City 2025"

# Shared test helpers

# Build full-refuel records from distance/litre pairs. The first fill only sets the starting odometer.
def readings(intervals):
    odometer = 10000
    entries = [FuelEntry(PLATE, "01-01-2025", odometer, 20, entry_id=1)]
    for number, (distance, litres) in enumerate(intervals, 2):
        odometer += distance
        day = (date(2025, 1, 1) + timedelta(days=number - 1)).strftime("%d-%m-%Y")
        entries.append(FuelEntry(PLATE, day, odometer, litres, entry_id=number))
    return entries

# Use 20 litres per interval when a test only needs a simple sequence of km/L values.
def analyse(efficiencies):
    return FuelEfficiencyAnalyser().analyse(readings([(round(value * 20), 20) for value in efficiencies]))

# Each test gets its own folder. Pass values to start with fuel history, or leave it empty.
def service(tmp_path, values=None, history=None):
    data = FuelDataManager(data_dir=str(tmp_path))
    fuel = FuelService(data.fuel, data.fuel_assessments,
                       maintenance_history=data.history if history is None else history,
                       maintenance_rules=HistoryRules(), reviews=data.fuel_reviews)
    if values is not None:
        seed(fuel, values)
    return fuel

# Save the readings through the real service so its normal validation still runs.
def seed(fuel, efficiencies):
    entries = readings([(round(value * 20), 20) for value in efficiencies])
    for entry in entries:
        fuel.add_refuel(PLATE, entry.refuel_date, entry.odometer_km, entry.litres)

# Add the next day's full refuel without repeating date and odometer calculations in every test.
def append(fuel, efficiency=15):
    last = fuel.get_history(PLATE)[-1]
    day = (datetime.strptime(last.refuel_date, "%d-%m-%Y") + timedelta(days=1)).strftime("%d-%m-%Y")
    return fuel.add_refuel(PLATE, day, last.odometer_km + round(efficiency * 20), 20)

# A small stand-in for saved maintenance records; it still separates vehicles by plate.
class History:
    def __init__(self, records):
        self.records = records

    def for_plate(self, plate):
        return [record for record in self.records if record["license_plate"] == plate]

# Use the same maintenance record shape that the real tracker expects.
def maintenance(day, km, plate=PLATE):
    return {"license_plate": plate, "part_name": "Engine Oil", "service_date": day,
            "service_odometer": km, "service_action": "replace", "notes": "private note"}

# Start with one complete, valid AI reply, then change only the fields a test is interested in.
def ai_answer(**changes):
    result = {"ai_status": "ok", "ai_provider": "Fake", "anomaly_status": "Normal",
              "trend": "Stable", "confidence": "Medium", "baseline_assessment": "Suitable",
              "pattern": "No clear drop", "flagged_entry_ids": [],
              "summary": "The saved fuel pattern has been assessed; driving context is unknown.",
              "possible_factors": [], "suggested_checks": ["Continue recording full-tank refuels"]}
    result.update(changes)
    return result

# Count requests and remember the evidence sent to AI. This makes unwanted repeat requests visible.
class RecordingAI:
    def __init__(self, **changes):
        self.calls = 0
        self.last_dashboard = None
        self.answer = ai_answer(**changes)

    def analyse_fuel(self, dashboard, car_model):
        self.calls += 1
        self.last_dashboard = dashboard
        result = dict(self.answer)
        if result["anomaly_status"] in ("Monitor", "Unusual drop"):
            ids = dashboard["eligible_alert_entry_ids"]
            result["flagged_entry_ids"] = list(ids if result["pattern"] in ("Repeated", "Gradual") else ids[-1:])
        return result

# Return the text we supply, or raise a test error. No network connection is involved.
class Provider:
    is_available = True

    def __init__(self, reply, name="Fake provider"):
        self.reply = reply
        self.name = name
        self.calls = 0
        self.prompt = None

    def ask(self, prompt, manual_path, part_name):
        self.calls += 1
        self.prompt = prompt
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

# Supply menu choices automatically. These checks focus on the controller, so the display methods do nothing.
class MenuIO:
    def __init__(self):
        self.choices = iter(["1", "2", "3", "4", "5", "6", "7"])
        self.messages = []
        self.results = []

    def prompt_fuel_menu(self):
        return next(self.choices)

    def prompt_fuel_entry(self, old=None):
        return {"refuel_date": "10-01-2025", "odometer_km": 12460 if old is None else 12480, "litres": 20}

    def prompt_fuel_choice(self, history, action):
        return history[-1]

    def confirm_action(self, question):
        return True

    def prompt_fuel_review(self, alert):
        return "ordinary_variation"

    def display_message(self, message):
        self.messages.append(message)

    def display_fuel_dashboard(self, dashboard):
        pass

    def display_fuel_history(self, entries):
        pass

    def display_fuel_ai(self, result):
        self.results.append(result)

# The fuel menu only needs these two profile fields; full application tests use a real UserProfile.
class User:
    license_plate = PLATE
    car_model = CAR_MODEL
# Act like an unavailable AI service while recording how many requests were attempted.
class UnavailableAI:
    def __init__(self):
        self.calls = 0

    def analyse_fuel(self, dashboard, car_model):
        self.calls += 1
        return {"ai_status": "unavailable", "message": "Test provider is unavailable"}

# Fail immediately if a path that should skip AI accidentally asks for a report.
class ForbiddenAI:
    def analyse_fuel(self, dashboard, car_model):
        raise AssertionError("AI must not be called for this request")

# Keep the usual vehicle and rule settings in one place; every caller still supplies its own fake AI.
def request_report(fuel, ai, model=CAR_MODEL, **options):
    return fuel.analyse_with_ai(PLATE, ai, model, FuelLogicManager(), **options)


# Run the actual login and menus with typed answers supplied by the test.
# Copying cars.json is safe here: it is read-only reference data, not a user's history.
def run_app(tmp_path, monkeypatch, answers, values=None):
    project = Path(__file__).resolve().parents[1]
    shutil.copy(project / "data" / "cars.json", tmp_path / "cars.json")
    data = FuelDataManager(data_dir=str(tmp_path), project_dir=str(project))
    assert data.users.save(UserProfile("Fuel Test", PLATE, CAR_MODEL, "Brand New", "01-01-2030"))
    if values is not None:
        service(tmp_path, values)
    provider = Provider(json.dumps(ai_answer()))
    answers = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    App(FuelIOManager(), data, FuelAIManager([provider], retry_delay=0), FuelLogicManager()).run()
    return data, provider

# Open a real saved alert using a fake AI decision, ready for the review and recovery tests.
def open_alert(fuel):
    ai = RecordingAI(anomaly_status="Unusual drop", pattern="Repeated",
                     trend="Worsening", confidence="High")
    result = request_report(fuel, ai)
    assert result["ai_status"] == "ok" and result["saved"] and result["alert_active"]
    return result

# One starting fill does not create an interval. We need eight usable intervals before assessment.
@pytest.mark.parametrize("count", range(8))
def test_incomplete_history_cannot_be_assessed(count):
    result = analyse([15] * count)
    assert not result["analysis_ready"]
    assert result["latest_status"] == "Not assessed"
    assert result["baseline_km_per_l"] is None
    assert not result["alert_active"]
    assert result["intervals_needed"] == 8 - count

# Nine fills give five older intervals and three recent ones. Every recent check must use the same comparison.
def test_ninth_full_refuel_uses_five_older_intervals_and_one_shared_baseline():
    result = analyse([15] * 5 + [12, 12, 12])
    assert result["baseline_count"] == 5
    assert result["baseline_entry_ids"] == [2, 3, 4, 5, 6]
    assert result["recent_count"] == 3
    assert {point["baseline_km_per_l"] for point in result["recent_individual_checks"]} == {15}
    assert result["recent_average_km_per_l"] == 12
    assert result["recent_drop_percent"] == 20

# Five older intervals is the minimum, not a limit. More eligible older history should still count.
def test_baseline_uses_all_eligible_older_intervals_not_a_fixed_five():
    result = analyse([15] * 14)
    assert result["baseline_count"] == 11
    assert result["latest_status"] == "Not assessed"
    assert result["analysis_ready"]

# A larger refuel should carry more weight. These numbers give 1,650 km / 100 L = 16.5 km/L.
def test_baseline_uses_total_distance_divided_by_total_litres():
    older = [(150, 10), (600, 30), (300, 20), (300, 20), (300, 20)]
    result = FuelEfficiencyAnalyser().analyse(readings(older + [(330, 20)] * 3))
    assert result["baseline_km_per_l"] == 16.5
    assert result["overall_average_km_per_l"] == 16.5

# The recent tanks have different sizes: 1,000 km / 70 L gives 14.29 km/L, not an equal average of ratios.
def test_recent_window_is_weighted_by_litres():
    result = FuelEfficiencyAnalyser().analyse(readings([(300, 20)] * 5 +
                                                      [(300, 20), (600, 40), (100, 10)]))
    assert result["recent_average_km_per_l"] == 14.29
    assert result["recent_drop_percent"] == 4.8
    assert not result["alert_active"]
    assert "persistent_drop" not in result

# A poor interval is evidence for AI to assess. The calculator must not decide whether a fault repeats.
@pytest.mark.parametrize("recent", [[15, 15, 10], [12, 12, 12], [10, 10, 15], [15, 12, 12]])
def test_math_alone_does_not_decide_persistence(recent):
    dashboard = analyse([15] * 5 + recent)
    assert dashboard["latest_status"] == "Not assessed"
    assert not dashboard["alert_active"]
    assert all("status" not in point for point in dashboard["recent_individual_checks"])

# Keep the original comparison while an alert is open, even after many more poor readings arrive.
def test_persistent_deterioration_never_becomes_normal_without_review(tmp_path):
    fuel = service(tmp_path, [15] * 5 + [12] * 3)
    open_alert(fuel)
    for _ in range(12):
        append(fuel, 12)
    result = service(tmp_path).get_dashboard(PLATE)
    assert result["baseline_km_per_l"] == 15
    assert result["baseline_count"] == 5
    assert result["alert_active"] and result["assessment_pending"]

# Recovery, an unclear reply or an outage must not silently close an alert that still needs a review.
@pytest.mark.parametrize("status,new_intervals", [
    ("Normal", 1), ("Unclear", 1), ("Normal", 3), ("unavailable", 1),
])
def test_new_reports_do_not_close_an_unreviewed_alert(tmp_path, status, new_intervals):
    fuel = service(tmp_path, [15] * 5 + [10] * 3)
    first = open_alert(fuel)
    for _ in range(new_intervals):
        append(fuel, 15)
    ai = UnavailableAI() if status == "unavailable" else RecordingAI(anomaly_status=status)
    result = request_report(fuel, ai)
    assert result["alert_active"] and result["baseline_frozen"]
    if status == "unavailable":
        assert result["ai_status"] == "unavailable" and not result["saved"]
        assert len(FuelDataManager(data_dir=str(tmp_path)).fuel_assessments.for_plate(PLATE)) == 1
    else:
        assert result["anomaly_status"] == status and result["saved"]
        expected = "ASSESSMENT UNCLEAR" if status == "Unclear" else "REVIEW OPEN ALERT"
        assert result["fuel_outcome"].startswith(expected)
    restored = service(tmp_path).get_dashboard(PLATE)
    assert restored["alert_active"] and restored["baseline_km_per_l"] == 15
    assert restored["alert"]["first_entry_id"] == first["alert"]["first_entry_id"]
# The 15% and 20% figures are guidance. Crossing either value must not let Python label an anomaly.
@pytest.mark.parametrize("drop", [14.9, 15, 19.9, 20, 40])
def test_reference_percentages_do_not_create_warnings(drop):
    value = 15 * (1 - drop / 100)
    result = analyse([15] * 5 + [value] * 3)
    assert result["thresholds"] == {"monitor_percent": 15, "investigate_percent": 20}
    assert result["latest_status"] == "Not assessed"
    assert not result["alert_active"]
    assert not hasattr(FuelEfficiencyAnalyser, "classify_drop")

# Ordinary variation stays in history. Restarting the tracker must not reopen the same reviewed period.
def test_ordinary_variation_review_retains_records_and_does_not_reopen_on_old_readings(tmp_path):
    fuel = service(tmp_path, [15] * 5 + [10] * 3)
    open_alert(fuel)
    before = [entry.to_dict() for entry in fuel.get_history(PLATE)]
    result = fuel.review_alert(PLATE, "ordinary_variation")
    assert result["assessment_pending"]
    assert result["alert_active"] is False
    assert result["reviewed_ordinary_intervals"] == 3
    assert [entry.to_dict() for entry in fuel.get_history(PLATE)] == before
    restarted = service(tmp_path)
    assert restarted.get_dashboard(PLATE)["alert_active"] is False
    append(restarted, 15)
    result = restarted.get_dashboard(PLATE)
    assert result["alert_active"] is False
    assert result["baseline_count"] == 6
    assert result["ignored_review_count"] == 0

# A fault period stays in the overall history, but it must not lower the healthy comparison average.
def test_confirmed_fault_review_excludes_period_only_from_baseline(tmp_path):
    fuel = service(tmp_path, [15] * 5 + [10] * 3)
    open_alert(fuel)
    result = fuel.review_alert(PLATE, "confirmed_fault")
    assert result["excluded_fault_intervals"] == 3
    assert result["overall_average_km_per_l"] == 13.12
    assert len(fuel.get_history(PLATE)) == 9
    assert result["recent_count"] == 0
    restarted = service(tmp_path)
    append(restarted, 15)
    result = restarted.get_dashboard(PLATE)
    assert result["baseline_km_per_l"] == 15
    assert result["alert_active"] is False
    assert result["recent_count"] == 1

# Changed conditions need eight new intervals; a fault review needs three recent ones. AI must wait.
@pytest.mark.parametrize("decision,needed,expected_baseline", [
    ("changed_conditions", 8, 12), ("confirmed_fault", 3, 15),
])
def test_review_waits_for_enough_new_intervals(tmp_path, decision, needed, expected_baseline):
    fuel = service(tmp_path, [15] * 5 + [10] * 3)
    open_alert(fuel)
    reviewed = fuel.review_alert(PLATE, decision)
    if decision == "changed_conditions":
        assert reviewed["baseline_km_per_l"] is None and reviewed["intervals_needed"] == 8
    for count in range(needed):
        result = request_report(fuel, ForbiddenAI())
        assert result["ai_status"] == "insufficient_history"
        if decision == "changed_conditions":
            assert f"needed: {needed - count}." in result["message"]
        else:
            assert f"Record {needed - count} more" in result["message"]
        append(fuel, 12)
    ready = service(tmp_path).get_dashboard(PLATE)
    assert ready["baseline_km_per_l"] == expected_baseline and ready["baseline_count"] == 5
    assert not ready["alert_active"]
    if decision == "changed_conditions":
        assert ready["latest_status"] == "Not assessed"
    ai = RecordingAI()
    assert request_report(fuel, ai)["ai_status"] == "ok" and ai.calls == 1

# An old review describes the old measurements. Editing those measurements should make that review outdated.
def test_edit_invalidates_a_review_bound_to_old_measurements(tmp_path):
    fuel = service(tmp_path, [15] * 5 + [10] * 3)
    open_alert(fuel)
    fuel.review_alert(PLATE, "confirmed_fault")
    last = fuel.get_history(PLATE)[-1]
    fuel.update_refuel(PLATE, last.entry_id, last.refuel_date, last.odometer_km, 19)
    result = fuel.get_dashboard(PLATE)
    assert result["ignored_review_count"] == 1
    assert not result["alert_active"] and result["assessment_pending"]
    open_alert(fuel)
    assert fuel.get_dashboard(PLATE)["alert_active"]

# If the reviewed endpoint is deleted, its old decision can no longer be applied to the remaining records.
def test_deleted_review_endpoint_cannot_silently_keep_its_decision(tmp_path):
    fuel = service(tmp_path, [15] * 5 + [10] * 3)
    open_alert(fuel)
    fuel.review_alert(PLATE, "confirmed_fault")
    assert fuel.delete_refuel(PLATE, fuel.get_history(PLATE)[-1].entry_id)
    result = fuel.get_dashboard(PLATE)
    assert result["ignored_review_count"] == 1
    assert result["latest_status"] == "Not assessed"
    assert not result["analysis_ready"]

# A later gap does not change an earlier alert period. We should still be able to review that period.
def test_review_still_saves_when_a_later_record_only_starts_a_new_segment(tmp_path):
    fuel = service(tmp_path, [15] * 5 + [10] * 3)
    open_alert(fuel)
    missing = append(fuel, 10)
    append(fuel, 10)
    fuel.delete_refuel(PLATE, missing.entry_id)
    result = fuel.review_alert(PLATE, "ordinary_variation")
    assert not result["alert_active"] and result["ignored_review_count"] == 0
    assert result["recent_count"] == 0
# Review choices only make sense when there is an alert to review.
@pytest.mark.parametrize("decision", ["ordinary_variation", "confirmed_fault", "changed_conditions"])
def test_review_requires_an_open_alert(tmp_path, decision):
    with pytest.raises(ValueError, match="no open"):
        service(tmp_path).review_alert(PLATE, decision)

# If saving the review is unsafe, leave the original file and the open alert alone.
def test_corrupt_review_file_is_not_overwritten_and_alert_remains_open(tmp_path):
    fuel = service(tmp_path, [15] * 5 + [10] * 3)
    open_alert(fuel)
    path = tmp_path / "fuel_reviews.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(OSError, match="alert remains open"):
        fuel.review_alert(PLATE, "ordinary_variation")
    assert path.read_text(encoding="utf-8") == "{broken"
    assert fuel.get_dashboard(PLATE)["alert_active"] is True

# Check fuel dates against maintenance mileage too, including earlier records and impossible jumps.
@pytest.mark.parametrize("history_day,history_km,fuel_day,fuel_km,allowed", [
    ("01-11-2025", 50000, "05-11-2025", 2000, False),
    ("05-11-2025", 50000, "01-11-2025", 48000, True),
    ("01-11-2025", 50000, "01-11-2025", 50000, True),
    ("09-11-2025", 50000, "01-11-2025", 52000, False),
    ("01-11-2025", 50000, "02-11-2025", 80000, False),
])
def test_fuel_validation_considers_maintenance_dates_and_mileage(
        tmp_path, history_day, history_km, fuel_day, fuel_km, allowed):
    fuel = service(tmp_path, history=History([maintenance(history_day, history_km)]))
    if allowed:
        assert fuel.add_refuel(PLATE, fuel_day, fuel_km, 20).odometer_km == fuel_km
    else:
        with pytest.raises(ValueError, match="maintenance history"):
            fuel.add_refuel(PLATE, fuel_day, fuel_km, 20)
        assert fuel.get_history(PLATE) == []

# Another vehicle's mileage is unrelated and must not block this driver's refuel.
def test_other_vehicles_maintenance_does_not_block_a_refuel(tmp_path):
    fuel = service(tmp_path, history=History([maintenance("01-11-2025", 50000, "OTHER")]))
    assert fuel.add_refuel(PLATE, "05-11-2025", 2000, 20).odometer_km == 2000

# A rejected edit must leave the previously saved measurement unchanged.
def test_edit_rejects_backwards_mileage_without_changing_saved_values(tmp_path):
    fuel = service(tmp_path, history=History([maintenance("01-11-2025", 50000)]))
    old = fuel.add_refuel(PLATE, "02-11-2025", 50100, 20)
    with pytest.raises(ValueError, match="maintenance history"):
        fuel.update_refuel(PLATE, old.entry_id, old.refuel_date, 2000, 20)
    assert fuel.get_history(PLATE)[0].odometer_km == 50100

# Try bad dates, invalid odometers, zero fuel, NaN and infinity before any record reaches storage.
@pytest.mark.parametrize("changes", [
    {"refuel_date": "31-02-2025"}, {"refuel_date": "2025-01-01"},
    {"odometer_km": -1}, {"odometer_km": True}, {"odometer_km": 2_000_001},
    {"odometer_km": 12.5}, {"litres": 0}, {"litres": -1}, {"litres": True},
    {"litres": float("nan")}, {"litres": float("inf")}, {"litres": 201},
    {"refuel_date": (date.today() + timedelta(days=1)).strftime("%d-%m-%Y")},
])
def test_invalid_measurements_are_rejected(changes):
    fields = {"refuel_date": "01-01-2025", "odometer_km": 10000, "litres": 20}
    fields.update(changes)
    with pytest.raises(ValueError):
        FuelEntry(PLATE, **fields)

# A second record cannot reuse the same odometer or move backwards in date.
def test_fuel_history_rejects_duplicates_and_reversed_dates(tmp_path):
    fuel = service(tmp_path)
    fuel.add_refuel(PLATE, "05-01-2025", 10000, 20)
    for day, km in [("06-01-2025", 10000), ("04-01-2025", 10300)]:
        with pytest.raises(ValueError):
            fuel.add_refuel(PLATE, day, km, 20)

# Deleting a fill breaks the measurement chain. Do not invent fuel use across the missing record.
def test_delete_does_not_bridge_the_missing_refuel(tmp_path):
    fuel = service(tmp_path, [15] * 4)
    fuel.delete_refuel(PLATE, fuel.get_history(PLATE)[1].entry_id)
    result = fuel.get_dashboard(PLATE)
    assert result["interval_count"] == 2
    assert result["total_distance_km"] == 600

# Bad JSON must be reported without replacing the user's existing fuel file.
def test_corrupt_measurement_file_is_not_overwritten(tmp_path):
    path = tmp_path / "fuel_history.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(OSError):
        service(tmp_path).add_refuel(PLATE, "01-01-2025", 10000, 20)
    assert path.read_text(encoding="utf-8") == "{broken"

# A saved report should survive a restart. A new fill makes it outdated, but only Analyse requests AI again.
def test_saved_report_is_reused_until_a_new_refuel_changes_the_data(tmp_path):
    fuel = service(tmp_path, [15] * 8)
    ai = RecordingAI()
    notices = []
    options = {"before_request": lambda: notices.append("new request")}
    first = request_report(fuel, ai, **options)
    again = request_report(service(tmp_path), ForbiddenAI(), **options)
    assert first["ai_status"] == "ok" and first["saved"]
    assert again["saved"] and again["reused"] and ai.calls == 1
    assert notices == ["new request"]
    append(fuel, 10)
    assert fuel.get_dashboard(PLATE)["assessment_pending"] and ai.calls == 1
    assert not fuel.get_dashboard(PLATE)["alert_active"]
    changed = request_report(fuel, ai, **options)
    assert changed["saved"] and not changed["reused"] and ai.calls == 2
    assert notices == ["new request", "new request"]

# AI needs a fresh assessment when maintenance or a review changes. Private notes should stay out of its input.
def test_maintenance_and_reviews_invalidate_cached_ai_reports(tmp_path):
    data = FuelDataManager(data_dir=str(tmp_path))
    history = History([])
    fuel = FuelService(data.fuel, data.fuel_assessments, maintenance_history=history,
                       maintenance_rules=HistoryRules(), reviews=data.fuel_reviews)
    seed(fuel, [15] * 5 + [10] * 3)
    ai = RecordingAI(anomaly_status="Unusual drop", pattern="Repeated")
    request_report(fuel, ai)
    history.records.append(maintenance("01-01-2024", 5000))
    request_report(fuel, ai)
    assert ai.calls == 2
    assert "license_plate" not in ai.last_dashboard["maintenance_history"][0]
    assert "notes" not in ai.last_dashboard["maintenance_history"][0]
    fuel.review_alert(PLATE, "ordinary_variation")
    ai.answer = ai_answer()
    request_report(fuel, ai)
    assert ai.calls == 3

# Reject unusable replies, including made-up record IDs, duplicate IDs and invalid confidence values.
@pytest.mark.parametrize("change", [
    {"trend": "unknown"},
    {"confidence": 1},
    {"pattern": "Unknown"},
    {"baseline_assessment": "Healthy"},
    {"summary": "short"},
    {"possible_factors": [1]},
    {"suggested_checks": [1]},
    {"anomaly_status": "Potential abnormal consumption"},
    {"anomaly_status": "Monitor", "flagged_entry_ids": []},
    {"flagged_entry_ids": [9]},
    {"anomaly_status": "Monitor", "flagged_entry_ids": [6]},
    {"anomaly_status": "Monitor", "flagged_entry_ids": [10]},
    {"anomaly_status": "Monitor", "flagged_entry_ids": [9, 9]},
    {"anomaly_status": "Monitor", "flagged_entry_ids": [True]},
    {"anomaly_status": "Monitor", "flagged_entry_ids": ["9"]},
    {"suggested_checks": []},
    {"confidence": "99%"}
])
def test_invalid_ai_fields_and_flagged_records_are_rejected(change):
    dashboard = analyse([15] * 5 + [10] * 3)
    assert FuelAIAdvisor.validate_response(json.dumps(ai_answer(**change)), dashboard) is None

# If the first provider fails, try the next. Send the measurements and saved maintenance without private details.
def test_ai_falls_back_and_receives_both_checks_and_saved_maintenance_only():
    dashboard = analyse([15] * 5 + [12] * 3)
    dashboard["maintenance_history"] = [{"part_name": "Engine Oil", "service_date": "01-01-2025"}]
    first = Provider("not JSON", "First")
    second = Provider(json.dumps(ai_answer()), "Second")
    result = FuelAIAdvisor([first, second]).analyse(dashboard, CAR_MODEL)
    assert result["ai_provider"] == "Second" and first.calls == second.calls == 1
    data = json.loads(second.prompt.splitlines()[-1])
    assert len(data["measurements"]["recent_individual_checks"]) == 3
    assert data["measurements"]["recent_average_km_per_l"] == 12
    assert data["maintenance_history"][0]["part_name"] == "Engine Oil"
    assert "Not collected" in data["driving_context"] and PLATE not in second.prompt
    assert all("status" not in item for item in data["measurements"]["recent_individual_checks"])
    assert "guidance, not automatic cut-offs" in second.prompt
    assert "confidence describes support for the FUEL PATTERN" in second.prompt

# An empty or unfinished dashboard must return straight away instead of contacting a provider.
@pytest.mark.parametrize("count", [None, 0, 1, 7])
def test_ai_provider_is_skipped_when_the_dashboard_is_not_ready(count):
    dashboard = {} if count is None else analyse([15] * count)
    provider = Provider(json.dumps(ai_answer()))
    result = FuelAIAdvisor([provider]).analyse(dashboard, CAR_MODEL)
    assert result["ai_status"] == "insufficient_history" and provider.calls == 0

# A timeout followed by broken JSON should produce a clear unavailable result instead of crashing.
def test_network_failure_and_failed_json_return_an_unavailable_report():
    result = FuelAIAdvisor([Provider(TimeoutError("test timeout")), Provider("bad JSON")]).analyse(
        analyse([15] * 8))
    assert result["ai_status"] == "unavailable"

# The same fuel evidence can lead to different advice when AI confidence or comparison suitability changes.
# High confidence supports the fuel pattern; it does not prove that a particular part has failed.
def test_ai_fields_meaningfully_change_follow_up():
    dashboard = analyse([15] * 5 + [12] * 3)
    logic = FuelLogicManager()
    reply = ai_answer(anomaly_status="Unusual drop", trend="Worsening", confidence="High",
                      pattern="Repeated", flagged_entry_ids=[7, 8, 9])
    strong = logic.evaluate_fuel(dashboard, reply)
    uncertain = logic.evaluate_fuel(dashboard, {**reply, "confidence": "Low"})
    unsuitable = logic.evaluate_fuel(dashboard, {**reply, "baseline_assessment": "Uncertain"})
    assert strong["fuel_outcome"].startswith("INSPECTION ADVISED")
    assert uncertain["fuel_outcome"].startswith("VERIFY")
    assert unsuitable["fuel_outcome"].startswith("VERIFY")
    assert "numeric_status" not in strong

# One poor tank deserves verification; it is not enough evidence for repeated deterioration.
def test_a_single_outlier_is_not_routed_as_persistent_deterioration():
    reply = ai_answer(anomaly_status="Unusual drop", trend="Worsening", confidence="High",
                      pattern="Isolated", flagged_entry_ids=[9])
    result = FuelLogicManager().evaluate_fuel(analyse([15] * 7 + [10]), reply)
    assert result["fuel_outcome"].startswith("VERIFY")

# Bad input should be re-prompted, and the selected review should apply to the whole alert period.
def test_cli_reasks_invalid_litres_and_accepts_a_whole_period_review(monkeypatch):
    answers = iter(["nan", "inf", "0", "201", "25.5", "bad", "2"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    io = FuelIOManager()
    assert io.prompt_fuel_litres("Litres") == 25.5
    assert io.prompt_fuel_review({"first_date": "01-01-2025", "last_date": "03-01-2025"}) == "confirmed_fault"

# The fuel feature should reuse the existing manager design rather than replace the rest of the application.
def test_fuel_extensions_remain_instances_of_original_managers(tmp_path):
    assert isinstance(FuelIOManager(), IOManager)
    assert isinstance(FuelDataManager(data_dir=str(tmp_path)), DataManager)
    assert isinstance(FuelAIManager([], retry_delay=0), AIManager)
    assert isinstance(FuelLogicManager(), LogicManager)

# Exercise the record and review actions with and without Analyse. Only a fresh analysis may request AI.
@pytest.mark.parametrize("analyse_requested", [False, True])
def test_menu_only_calls_ai_for_analyse_and_reuses_an_unchanged_report(tmp_path, analyse_requested):
    data = FuelDataManager(data_dir=str(tmp_path))
    fuel = service(tmp_path, [15] * 5 + [12] * 3)
    if not analyse_requested:
        open_alert(fuel)
    io = MenuIO()
    io.choices = iter(["1", "2", "3", "4"] + (["5", "5"] if analyse_requested else []) + ["6", "7"])
    ai = RecordingAI(anomaly_status="Unusual drop", pattern="Repeated") if analyse_requested else ForbiddenAI()
    user = User()
    assert FuelController(io, data, ai, FuelLogicManager()).run(user) is user
    if analyse_requested:
        assert ai.calls == 1 and len(io.results) == 2
        assert any(result["reused"] for result in io.results)
    else:
        assert io.results == []
    assert any("Review saved" in message for message in io.messages)
    assert not service(tmp_path).get_dashboard(PLATE)["alert_active"]

# Deleting this profile should remove its fuel records and reports while keeping the other vehicle intact.
def test_profile_cleanup_is_scoped_to_one_vehicle(tmp_path):
    data = FuelDataManager(data_dir=str(tmp_path))
    fuel = service(tmp_path, [15] * 5 + [10] * 3)
    open_alert(fuel)
    fuel.review_alert(PLATE, "ordinary_variation")
    request_report(fuel, RecordingAI())
    fuel.add_refuel("OTHER", "01-01-2025", 5000, 20)
    FuelController(MenuIO(), data, RecordingAI(), FuelLogicManager()).delete_profile_data(PLATE)
    assert data.fuel.for_plate(PLATE) == []
    assert data.fuel_assessments.for_plate(PLATE) == []
    assert data.fuel_reviews.for_plate(PLATE) == []
    assert len(data.fuel.for_plate("OTHER")) == 1

# A failed request or save is not a reusable report. Even an unusual-drop reply must not create an unsaved alert.
@pytest.mark.parametrize("failure,status", [
    ("provider", "Normal"), ("storage", "Normal"), ("storage", "Unusual drop"),
])
def test_failed_requests_and_failed_saves_do_not_become_cached_reports(tmp_path, failure, status):
    fuel = service(tmp_path, [15] * 5 + [10] * 3)
    path = tmp_path / "fuel_assessments.json"
    if failure == "storage":
        path.write_text("{broken", encoding="utf-8")
    ai = UnavailableAI() if failure == "provider" else RecordingAI(
        anomaly_status=status, pattern="Isolated" if status == "Unusual drop" else "No clear drop")
    for _ in range(2):
        result = request_report(fuel, ai)
        assert not result["saved"] and not result["reused"] and not result["alert_active"]
        if failure == "provider":
            assert result["ai_status"] == "unavailable" and result["ai_anomaly_status"] is None
        else:
            assert result["ai_status"] == "ok" and "could not be saved" in result["message"]
    assert ai.calls == 2 and not service(tmp_path).get_dashboard(PLATE)["alert_active"]
    if failure == "storage":
        assert path.read_text(encoding="utf-8") == "{broken"
    else:
        assert not path.exists()

# Use the real login and menus to check that the first fill saves and early analysis returns safely.
def test_real_menu_saves_a_first_refuel_and_blocks_early_analysis(tmp_path, monkeypatch, capsys):
    data, provider = run_app(tmp_path, monkeypatch,
                            ["1", PLATE, "11", "1", "01-01-2025", "50,000", "32.5", "5", "2", "7", "12"])
    output = capsys.readouterr().out
    assert len(data.fuel.for_plate(PLATE)) == 1 and provider.calls == 0
    entry = data.fuel.for_plate(PLATE)[0]
    assert (entry.refuel_date, entry.odometer_km, entry.litres) == ("01-01-2025", 50000, 32.5)
    assert "Fuel Consumption Tracker" in output and "Not enough valid fuel history" in output
    assert "AI report unavailable" not in output and "Goodbye!" in output

# Try every record count below nine. None should call AI, save a report or display a new-request notice.
@pytest.mark.parametrize("record_count", range(9))
def test_empty_and_partial_history_returns_before_any_ai_call(tmp_path, record_count):
    values = [15] * (record_count - 1) if record_count else None
    fuel = service(tmp_path, values)
    notices = []
    result = request_report(fuel, ForbiddenAI(), before_request=lambda: notices.append("new request"))
    assert result["ai_status"] == "insufficient_history"
    assert not result["saved"] and not result["reused"] and notices == []
    assert not (tmp_path / "fuel_assessments.json").exists()
    if record_count == 0:
        assert "No fuel records yet" in result["message"]
    else:
        assert "normally 9 full refuel records" in result["message"]
        assert f"needed: {9 - record_count}." in result["message"]

# A matching saved report cannot bypass the minimum-history check.
def test_validation_also_blocks_an_old_learning_period_report(tmp_path):
    data = FuelDataManager(data_dir=str(tmp_path))
    fuel = service(tmp_path)
    key = fuel.data_key(fuel.get_dashboard(PLATE), CAR_MODEL)
    assert data.fuel_assessments.save(PLATE, key, ai_answer())
    result = request_report(fuel, ForbiddenAI())
    assert result["ai_status"] == "insufficient_history"
    assert result["reused"] is False

# Reports from the older numerical-warning format need reassessment, even when their data key matches.
@pytest.mark.parametrize("old_format", ["missing_decision", "numerical_warning"])
def test_old_report_formats_are_not_reused_as_ai_decisions(tmp_path, old_format):
    data = FuelDataManager(data_dir=str(tmp_path))
    fuel = service(tmp_path, [15] * 8)
    if old_format == "missing_decision":
        old = ai_answer()
        old.pop("anomaly_status")
        old.pop("flagged_entry_ids")
    else:
        old = {"ai_status": "ok", "numeric_status": "Potential abnormal consumption",
               "baseline_frozen": True, "summary": "An older report without an AI anomaly decision"}
    key = fuel.data_key(fuel.get_dashboard(PLATE), CAR_MODEL)
    assert data.fuel_assessments.save(PLATE, key, old)
    dashboard = fuel.get_dashboard(PLATE)
    assert dashboard["assessment_pending"] and not dashboard["alert_active"]
    assert dashboard["latest_status"] == "Not assessed"
    ai = RecordingAI()
    result = request_report(fuel, ai)
    assert ai.calls == 1 and result["saved"] and not result["reused"]
    assert request_report(service(tmp_path), ForbiddenAI())["reused"]
    assert len(data.fuel_assessments.for_plate(PLATE)) == 2

# Nine records are not always eight usable intervals: a deleted middle fill leaves a measurement gap.
def test_deletion_can_make_nine_remaining_records_insufficient(tmp_path):
    fuel = service(tmp_path, [15] * 9)
    fuel.delete_refuel(PLATE, fuel.get_history(PLATE)[1].entry_id)
    assert len(fuel.get_history(PLATE)) == 9
    assert fuel.get_dashboard(PLATE)["interval_count"] == 7
    result = request_report(fuel, ForbiddenAI())
    assert result["ai_status"] == "insufficient_history"

# With no records, show the reason and return to the menu without progress text or a saved-report notice.
def test_real_menu_empty_analysis_shows_the_reason_without_requesting_ai(tmp_path, monkeypatch, capsys):
    _, provider = run_app(tmp_path, monkeypatch, ["1", PLATE, "11", "5", "7", "12"])
    output = capsys.readouterr().out
    assert "No fuel records yet" in output and "Goodbye!" in output and provider.calls == 0
    assert all(text not in output for text in (
        "AI report unavailable", "Generating a new AI report", "Report previously generated",
        "Checking fuel history", "A new AI request may take a moment"))

# The second Analyse selection should show the saved report immediately and should not print the fuel table again.
def test_real_menu_generates_once_and_then_shows_the_saved_report(tmp_path, monkeypatch, capsys):
    _, provider = run_app(tmp_path, monkeypatch, ["1", PLATE, "11", "5", "5", "7", "12"],
                         values=[15] * 5 + [12] * 3)
    output = capsys.readouterr().out
    assert provider.calls == 1 and output.count("Generating a new AI report...") == 1
    assert output.count("Report previously generated. No data has changed; showing saved report.") == 1
    assert output.count("--- Fuel AI summary ---") == 2
    assert all(text not in output for text in (
        "--- Fuel consumption history ---", "Checking fuel history and saved report",
        "A new AI request may take a moment", "Individual status at the time", "Baseline: Updating"))
    first = output.index("--- Fuel AI summary ---")
    saved = output.index("Report previously generated.")
    second = output.index("--- Fuel AI summary ---", first + 1)
    assert first < saved < second and "Goodbye!" in output

# Two failed Analyse attempts should show two real failures, not claim that a saved report was reused.
def test_failed_ai_request_is_not_described_as_a_saved_report(tmp_path, monkeypatch, capsys):
    data = FuelDataManager(data_dir=str(tmp_path))
    seed(service(tmp_path), [15] * 8)
    choices = iter(["5", "5", "7"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(choices))
    ai = UnavailableAI()
    FuelController(FuelIOManager(), data, ai, FuelLogicManager()).run(User())
    output = capsys.readouterr().out
    assert ai.calls == 2 and output.count("Generating a new AI report...") == 2
    assert "Report previously generated" not in output
    assert output.count("AI report unavailable:") == 2

# Hold the measurements constant and change the AI reply. The anomaly category must follow the AI decision.
@pytest.mark.parametrize("status", ["Normal", "Monitor", "Unusual drop", "Unclear"])
def test_ai_owns_the_anomaly_category_for_the_same_evidence(tmp_path, status):
    fuel = service(tmp_path, [12, 18, 10, 20, 15] + [12] * 3)
    before = [entry.to_dict() for entry in fuel.get_history(PLATE)]
    assert fuel.get_dashboard(PLATE)["recent_drop_percent"] == 20
    assert not fuel.get_dashboard(PLATE)["alert_active"]
    pattern = "Repeated" if status in ("Monitor", "Unusual drop") else "Unclear"
    ai = RecordingAI(anomaly_status=status, pattern=pattern, baseline_assessment="Uncertain")
    result = request_report(fuel, ai)
    assert result["anomaly_status"] == status and result["saved"]
    assert result["alert_active"] == (status in ("Monitor", "Unusual drop"))
    assert [entry.to_dict() for entry in fuel.get_history(PLATE)] == before
    again = request_report(service(tmp_path), ForbiddenAI())
    assert again["reused"] and ai.calls == 1

# AI may flag a pattern below the reference percentages; Python must not overwrite that assessment.
def test_percentages_are_guidance_not_python_anomaly_boundaries(tmp_path):
    fuel = service(tmp_path, [15] * 5 + [13.5] * 3)
    assert fuel.get_dashboard(PLATE)["recent_drop_percent"] == 10
    reply = request_report(fuel, RecordingAI(anomaly_status='Monitor', pattern='Repeated'))
    assert reply["anomaly_status"] == "Monitor" and reply["alert_active"]

# An unclear assessment is still a report we can reuse, but it should not open a new alert.
def test_unclear_is_saved_and_reused_without_opening_a_new_alert(tmp_path):
    fuel = service(tmp_path, [15] * 5 + [10] * 3)
    ai = RecordingAI(anomaly_status="Unclear", confidence="Low", pattern="Unclear")
    result = request_report(fuel, ai)
    assert result["saved"] and result["fuel_outcome"].startswith("ASSESSMENT UNCLEAR")
    assert not result["alert_active"] and not fuel.get_dashboard(PLATE)["baseline_frozen"]
    cached = request_report(service(tmp_path), ForbiddenAI())
    assert cached["anomaly_status"] == "Unclear" and cached["reused"]

# Once a period is reviewed as ordinary variation, AI must not reopen it using those same interval IDs.
def test_an_ordinary_review_prevents_ai_from_reopening_the_same_interval_ids(tmp_path):
    fuel = service(tmp_path, [15] * 5 + [10] * 3)
    open_alert(fuel)
    fuel.review_alert(PLATE, "ordinary_variation")
    assert fuel.get_dashboard(PLATE)["eligible_alert_entry_ids"] == []
    provider = Provider(json.dumps(ai_answer(anomaly_status="Unusual drop", flagged_entry_ids=[9])))
    result = request_report(fuel, FuelAIManager([provider], retry_delay=0))
    assert result["ai_status"] == "unavailable" and not fuel.get_dashboard(PLATE)["alert_active"]

# A different vehicle model changes the assessment context, so the old report must be reassessed.
def test_changing_the_car_model_invalidates_the_saved_report(tmp_path):
    fuel = service(tmp_path, [15] * 8)
    ai = RecordingAI()
    request_report(fuel, ai)
    assert not fuel.get_dashboard(PLATE, CAR_MODEL)["assessment_pending"]
    assert fuel.get_dashboard(PLATE, "Mazda 3 Hatchback 2020")["assessment_pending"]
    result = request_report(fuel, ai, model='Mazda 3 Hatchback 2020')
    assert ai.calls == 2 and not result["reused"]

# Reject damaged comparison values instead of trusting a saved alert with the wrong records or numbers.
@pytest.mark.parametrize("damage", [
    {"entry_ids": [{}, 3, 4, 5, 6]}, {"entry_ids": [2, 3, 4, 5, 99]},
    {"range": ["bad", 15]}, {"km_per_l": 1234}, {"litres": False},
])
def test_damaged_saved_comparison_is_not_used_or_reused(tmp_path, damage):
    fuel = service(tmp_path, [15] * 5 + [10] * 3)
    open_alert(fuel)
    path = tmp_path / "fuel_assessments.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    records[-1]["result"]["comparison_reference"].update(damage)
    path.write_text(json.dumps(records), encoding="utf-8")
    assert not service(tmp_path).get_dashboard(PLATE)["alert_active"]
    ai = RecordingAI()
    report = request_report(fuel, ai)
    assert ai.calls == 1 and report["saved"] and not report["reused"]

# Deleting a later fill must not erase a valid alert about an earlier period.
def test_deleting_a_later_refuel_does_not_hide_a_valid_earlier_ai_alert(tmp_path):
    fuel = service(tmp_path, [15] * 5 + [10] * 3)
    open_alert(fuel)
    later = append(fuel, 10)
    fuel.delete_refuel(PLATE, later.entry_id)
    dashboard = service(tmp_path).get_dashboard(PLATE)
    assert dashboard["alert_active"] and dashboard["baseline_km_per_l"] == 15
