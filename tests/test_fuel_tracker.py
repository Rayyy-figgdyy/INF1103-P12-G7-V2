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
