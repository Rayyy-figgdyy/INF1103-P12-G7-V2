# Guard against previously identified maintenance and storage errors.
"""Regression tests for five maintenance issues, with no live AI connection.

Each test uses small data examples so the reason for the expected behaviour
is easy to explain during the INF1103 demonstration. Fakes stand in for the
parts a test doesn't need (aggregation lets us pass them in).
"""
import datetime
import json

from ai.gemini_provider import GeminiProvider
from ai.groq_provider import GroqProvider
from ai_manager import AIManager
from controllers.check_controller import CheckController
from io_manager import IOManager
from logic.history_rules import HistoryRules
from logic_manager import LogicManager
from models.user_profile import UserProfile
from storage.json_repository import JsonRepository
from storage.json_store import JsonStore
from storage.service_history_repository import ServiceHistoryRepository
from test_ai_manager import GOOD, GROQ_ANSWER, fake_client, fake_groq


class FakeIO:
    """Scripted answers instead of the keyboard; messages are collected."""

    def __init__(self, confirm=True, choice=None, action="replace"):
        self.confirm = confirm
        self.choice = choice
        self.action = action
        self.output = []

    def confirm_action(self, prompt):
        return self.confirm

    def prompt_service_choice(self, records, purpose):
        return records[0] if self.choice is None else self.choice

    def prompt_service_action(self, part):
        return self.action

    def display_message(self, message):
        self.output.append(message)

    def display_list(self, records):
        self.output.extend(records)


class FakeHistory:
    def __init__(self, entries=None, update=None):
        self.entries = entries or []
        self.update_fn = update

    def for_plate(self, plate):
        return self.entries

    def update(self, record):
        return self.update_fn(record)


class FakeChecks:
    def __init__(self, records):
        self.records = records

    def for_plate(self, plate):
        return [record for record in self.records if record.get("license_plate") == plate]


class FakeData:
    def __init__(self, history, checks=None):
        self.history = history
        self.checks = checks


def make_controller(io, data) -> CheckController:
    rules = HistoryRules()
    return CheckController(io, data, LogicManager(), rules, brake_analyser=None,
                           pipeline=None, history=None)


def make_user(plate="SBA1234A") -> UserProfile:
    return UserProfile("Test", plate, "Mazda 3 Hatchback 2020", "Used", "01-01-2030")


def test_no_driving_pace_does_not_invent_service_date():
    # Only a mileage limit and no measured driving pace: cannot estimate a date.
    record = {
        "part_name": "Spark Plugs", "check_date": "14-10-2026",
        "last_service_date": "14-10-2026", "last_service_mileage": 1000,
        "current_odometer": 1000, "interval_km": 100000,
        "interval_months": 0, "urgency_score": 2,
    }
    facts = LogicManager().evaluate(record)
    assert facts["is_overdue"] is False
    assert facts["recommended_service_date"] == "N/A"
    assert IOManager.show_date("N/A") == "N/A"


def test_high_ai_urgency_still_provides_safety_date():
    # Even without mileage pace, high urgency gives a short action window.
    date = datetime.date(2026, 10, 14)
    assert LogicManager.recommend_service_date(date, False, 100000, None, 0, 8, False) == date + datetime.timedelta(days=3)


def test_old_history_action_can_be_confirmed_without_retyping_service():
    old_record = {
        "service_id": 9, "license_plate": "SBA1234A", "part_name": "Engine Oil",
        "service_date": "01-07-2026", "service_odometer": 20000, "notes": "invoice",
    }
    saved = []
    data = FakeData(FakeHistory(update=lambda record: saved.append(record) or True))
    controller = make_controller(FakeIO(confirm=True, action="replace"), data)

    assert controller.confirm_legacy_action(make_user(), "Engine Oil", [old_record])
    assert saved[0]["service_action"] == "replace"
    assert "service_action" not in old_record  # do not edit original in place


def test_declined_legacy_confirmation_leaves_data_unchanged():
    old = {"part_name": "Engine Oil", "service_id": 9}

    def must_not_save(record):
        raise AssertionError("must not save")

    controller = make_controller(FakeIO(confirm=False), FakeData(FakeHistory(update=must_not_save)))
    assert controller.confirm_legacy_action(make_user(), "Engine Oil", [old]) is False
    assert "service_action" not in old


def test_corrupt_history_json_blocks_write_and_preserves_content(tmp_path):
    path = tmp_path / "maintenance_history.json"
    original = '{"unfinished": [broken'
    path.write_text(original, encoding="utf-8")
    history = ServiceHistoryRepository(JsonRepository(str(path)))

    assert history.add({"part_name": "Brake Pads", "license_plate": "TEST"}) is None
    assert path.read_text(encoding="utf-8") == original
    assert not (tmp_path / "maintenance_history.json.tmp").exists()


def test_wrong_json_type_also_blocks_overwrite(tmp_path):
    path = tmp_path / "users.json"
    path.write_text('{"users": []}', encoding="utf-8")
    assert JsonStore(str(path)).write_list([{"name": "New User"}]) is False
    assert json.loads(path.read_text(encoding="utf-8")) == {"users": []}


def test_missing_json_file_can_be_created_normally(tmp_path):
    path = tmp_path / "checks.json"
    assert JsonStore(str(path)).write_list([{"part_name": "Engine Oil"}]) is True
    assert json.loads(path.read_text(encoding="utf-8"))[0]["part_name"] == "Engine Oil"


def test_malformed_gemini_response_immediately_uses_groq():
    gemini_calls, backup_calls = [], []
    ai = AIManager([GeminiProvider(fake_client(["not json", json.dumps(GOOD)], gemini_calls)),
                    GroqProvider(fake_groq([json.dumps(GROQ_ANSWER)], backup_calls))],
                   retry_delay=0)
    result = ai.process({"part_name": "Engine Oil", "current_odometer": 50000})
    assert result["ai_provider"] == "Groq (backup)"
    assert result["urgency_score"] == GROQ_ANSWER["urgency_score"]
    assert len(gemini_calls) == 1
    assert len(backup_calls) == 1


def test_recent_tyres_rotation_supersedes_old_urgent_check():
    old_check = {
        "part_name": "Tyres", "action": "rotate", "outcome": "URGENT - tyre rotation overdue",
        "last_service_date": "01-01-2026", "last_service_mileage": 10000,
    }
    new_history = [{"part_name": "Tyres", "service_action": "rotate",
                    "service_date": "01-10-2026", "service_odometer": 30000}]
    assert HistoryRules.is_check_superseded(old_check, new_history) is True


def test_inspection_does_not_supersede_required_replacement():
    old_check = {"part_name": "Coolant", "action": "replace",
                 "last_service_date": "01-01-2026", "last_service_mileage": 10000}
    inspection = [{"part_name": "Coolant", "service_action": "inspect",
                   "service_date": "01-10-2026", "service_odometer": 20000}]
    assert HistoryRules.is_check_superseded(old_check, inspection) is False


def test_urgent_menu_excludes_superseded_checks():
    plate = "TEST123"
    saved = [{"license_plate": plate, "part_name": "Tyres", "action": "rotate",
              "outcome": "URGENT - overdue", "risk_score": 80,
              "last_service_date": "01-01-2026", "last_service_mileage": 10000}]
    history = [{"part_name": "Tyres", "service_action": "rotate",
                "service_date": "01-10-2026", "service_odometer": 30000}]
    io = FakeIO()
    controller = make_controller(io, FakeData(FakeHistory(history), FakeChecks(saved)))
    controller.urgent(make_user(plate))
    assert not any(isinstance(item, dict) for item in io.output)
    assert "Nothing needs attention" in io.output[-1]


def test_history_crud_methods_required_by_the_controllers_are_available():
    # Protect against accidental removal of the maintenance-history data layer.
    names = ("load_all", "for_plate", "for_part", "add", "update", "delete", "delete_for_plate")
    for name in names:
        assert callable(getattr(ServiceHistoryRepository, name))


def test_edited_or_deleted_service_invalidates_old_check():
    previous = {"part_name": "Engine Oil", "action": "replace", "service_id": 7,
                "last_service_date": "01-01-2026", "last_service_mileage": 10000,
                "last_service_action": "replace"}
    # Removing the referenced service makes the saved assessment outdated.
    assert HistoryRules.is_check_superseded(previous, []) is True

    # Editing the same service ID also makes the old assessment outdated.
    edited = [{"service_id": 7, "part_name": "Engine Oil",
               "service_date": "02-01-2026", "service_odometer": 10000,
               "service_action": "replace"}]
    assert HistoryRules.is_check_superseded(previous, edited) is True

    # An unchanged saved service must not hide a current warning.
    unchanged = [{"service_id": 7, "part_name": "Engine Oil",
                  "service_date": "01-01-2026", "service_odometer": 10000,
                  "service_action": "replace"}]
    assert HistoryRules.is_check_superseded(previous, unchanged) is False
