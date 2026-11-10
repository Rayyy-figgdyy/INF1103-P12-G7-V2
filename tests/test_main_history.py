"""Check that CheckController passes raw brake-pad history to the AI pipeline."""
from controllers.check_controller import CheckController
from logic.brake_history_analyser import BrakeHistoryAnalyser
from logic.history_rules import HistoryRules
from models.user_profile import UserProfile


class FakeHistory:
    """Stands in for ServiceHistoryRepository: returns sample entries, no files."""

    def __init__(self, entries):
        self._entries = entries

    def for_part(self, plate, part_name):
        return self._entries


class FakeData:
    """Stands in for DataManager; only `history` is used by build_check_record."""

    def __init__(self, entries):
        self.history = FakeHistory(entries)


def make_controller(entries) -> CheckController:
    rules = HistoryRules()
    return CheckController(io=None, data=FakeData(entries), logic=None, rules=rules,
                           brake_analyser=BrakeHistoryAnalyser(rules),
                           pipeline=None, history=None)


def make_user() -> UserProfile:
    return UserProfile("Test", "TEST123", "Mazda 3 Hatchback 2020", "Used", "01-01-2030")


def test_main_includes_inspections_with_replacement_history():
    # Three replacements make the optional AI history analysis eligible.
    history = [
        {"part_name": "Brake Pads", "service_action": "replace",
         "service_date": date, "service_odometer": km}
        for date, km in [("01-01-2021", 20_000), ("01-01-2022", 40_000),
                         ("01-01-2023", 60_000)]
    ]
    history.append({"part_name": "Brake Pads", "service_action": "inspect",
                    "service_date": "01-01-2024", "service_odometer": 65_000})

    service = {"service_date": "01-01-2024", "service_odometer": 65_000,
               "service_action": "inspect"}
    interval = {"interval_km": 16_000, "interval_months": 12, "action": "inspect"}
    record = make_controller(history).build_check_record(
        make_user(), "Brake Pads", service, 70_000, interval, 2020)
    assert record["history_context"]["eligible"] is True
    assert record["history_context"]["replacement_count"] == 3
    assert record["brake_pad_history"] == history
    assert any(item["service_action"] == "inspect" for item in record["brake_pad_history"])


def test_main_falls_back_without_three_replacements():
    history = [
        {"part_name": "Brake Pads", "service_action": "replace",
         "service_date": "01-01-2022", "service_odometer": 20_000},
        {"part_name": "Brake Pads", "service_action": "replace",
         "service_date": "01-01-2023", "service_odometer": 40_000},
    ]
    service = {"service_date": "01-01-2023", "service_odometer": 40_000}
    interval = {"interval_km": 16_000, "interval_months": 12, "action": "inspect"}
    record = make_controller(history).build_check_record(
        make_user(), "Brake Pads", service, 70_000, interval, 2020)
    assert record["history_context"]["eligible"] is False
    assert "brake_pad_history" not in record


def test_other_parts_get_no_history_context():
    service = {"service_date": "01-01-2023", "service_odometer": 40_000,
               "service_action": "replace"}
    interval = {"interval_km": 10_000, "interval_months": 12, "action": "replace"}
    record = make_controller([]).build_check_record(
        make_user(), "Engine Oil", service, 45_000, interval, 2020)
    assert "history_context" not in record
    assert record["license_plate"] == "TEST123"
    assert record["last_service_action"] == "replace"
    assert record["interval_km"] == 10_000


class FakeAI:
    """A stand-in AIManager that records what it was asked."""

    def __init__(self):
        self.seen = None

    def process(self, record, manual_path=None):
        self.seen = record
        return {**record, "urgency_score": 9, "confidence": "High",
                "reasoning": "test", "manual_reference": "p.1",
                "overdue_summary": "", "answered_by": "Fake", "ai_status": "ok"}


def test_pipeline_runs_ai_first_then_logic():
    from logic_manager import LogicManager
    from controllers.maintenance_pipeline import MaintenancePipeline

    ai = FakeAI()
    record = {"license_plate": "TEST123", "part_name": "Engine Oil",
              "check_date": "01-06-2025", "last_service_date": "01-01-2025",
              "last_service_mileage": 40_000, "current_odometer": 45_000,
              "interval_km": 10_000, "interval_months": 12,
              "coe_expiry_date": "01-01-2030"}
    result = MaintenancePipeline(ai, LogicManager()).assess(record)
    assert ai.seen == record                     # C2: the AI saw the record first
    assert "outcome" in result and "risk_score" in result
    assert result["outcome"] == "URGENT - Service immediately"   # urgency 9 + High
