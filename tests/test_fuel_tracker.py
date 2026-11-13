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

# The 15% and 20% figures are guidance. Crossing either value must not let Python label an anomaly.
@pytest.mark.parametrize("drop", [14.9, 15, 19.9, 20, 40])
def test_reference_percentages_do_not_create_warnings(drop):
    value = 15 * (1 - drop / 100)
    result = analyse([15] * 5 + [value] * 3)
    assert result["thresholds"] == {"monitor_percent": 15, "investigate_percent": 20}
    assert result["latest_status"] == "Not assessed"
    assert not result["alert_active"]
    assert not hasattr(FuelEfficiencyAnalyser, "classify_drop")
