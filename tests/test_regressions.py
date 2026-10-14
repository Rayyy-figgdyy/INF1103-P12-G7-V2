# Guard against previously identified maintenance and storage errors.
"""Regression tests for five maintenance issues, with no live AI connection.

Each test uses small data examples so the reason for the expected behaviour
is easy to explain during the INF1103 demonstration.
"""
import datetime
import json

import ai_manager
import data_manager
import io_manager
import logic_manager
import main
from test_ai_manager import GOOD, GROQ_ANSWER, fake_client, fake_groq


def test_no_driving_pace_does_not_invent_service_date():
    # Only a mileage limit and no measured driving pace: cannot estimate a date.
    record = {
        "part_name": "Spark Plugs", "check_date": "14-10-2026",
        "last_service_date": "14-10-2026", "last_service_mileage": 1000,
        "current_odometer": 1000, "interval_km": 100000,
        "interval_months": 0, "urgency_score": 2,
    }
    facts = logic_manager.evaluate(record)
    assert facts["is_overdue"] is False
    assert facts["recommended_service_date"] == "N/A"
    assert io_manager.show_date("N/A") == "N/A"


def test_high_ai_urgency_still_provides_safety_date():
    # Even without mileage pace, high urgency gives a short action window.
    date = datetime.date(2026, 10, 14)
    assert logic_manager.recommend_service_date(date, False, 100000, None, 0, 8, False) == date + datetime.timedelta(days=3)


def test_old_history_action_can_be_confirmed_without_retyping_service(monkeypatch):
    old_record = {
        "service_id": 9, "license_plate": "SBA1234A", "part_name": "Engine Oil",
        "service_date": "01-07-2026", "service_odometer": 20000, "notes": "invoice",
    }
    saved = []
    monkeypatch.setattr(io_manager, "confirm_action", lambda prompt: True)
    monkeypatch.setattr(io_manager, "prompt_service_choice", lambda records, purpose: records[0])
    monkeypatch.setattr(io_manager, "prompt_service_action", lambda part: "replace")
    monkeypatch.setattr(io_manager, "display_message", lambda message: None)
    monkeypatch.setattr(data_manager, "update_service", lambda record: saved.append(record) or True)

    assert main.confirm_legacy_action({"license_plate": "SBA1234A"}, "Engine Oil", [old_record])
    assert saved[0]["service_action"] == "replace"
    assert "service_action" not in old_record  # do not edit original in place


def test_declined_legacy_confirmation_leaves_data_unchanged(monkeypatch):
    old = {"part_name": "Engine Oil", "service_id": 9}
    monkeypatch.setattr(io_manager, "confirm_action", lambda prompt: False)
    monkeypatch.setattr(io_manager, "display_message", lambda message: None)
    monkeypatch.setattr(data_manager, "update_service", lambda record: (_ for _ in ()).throw(AssertionError("must not save")))
    assert main.confirm_legacy_action({}, "Engine Oil", [old]) is False
    assert "service_action" not in old


def test_corrupt_history_json_blocks_write_and_preserves_content(tmp_path, monkeypatch):
    path = tmp_path / "maintenance_history.json"
    original = '{"unfinished": [broken'
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(data_manager, "HISTORY_FILE", str(path))

    assert data_manager.add_service({"part_name": "Brake Pads", "license_plate": "TEST"}) is None
    assert path.read_text(encoding="utf-8") == original
    assert not (tmp_path / "maintenance_history.json.tmp").exists()


def test_wrong_json_type_also_blocks_overwrite(tmp_path):
    path = tmp_path / "users.json"
    path.write_text('{"users": []}', encoding="utf-8")
    assert data_manager.write_list(str(path), [{"name": "New User"}]) is False
    assert json.loads(path.read_text(encoding="utf-8")) == {"users": []}


def test_missing_json_file_can_be_created_normally(tmp_path):
    path = tmp_path / "checks.json"
    assert data_manager.write_list(str(path), [{"part_name": "Engine Oil"}]) is True
    assert json.loads(path.read_text(encoding="utf-8"))[0]["part_name"] == "Engine Oil"


def test_malformed_gemini_response_immediately_uses_groq():
    gemini_calls, backup_calls = [], []
    result = ai_manager.process(
        {"part_name": "Engine Oil", "current_odometer": 50000},
        client=fake_client(["not json", json.dumps(GOOD)], gemini_calls),
        backup_client=fake_groq([json.dumps(GROQ_ANSWER)], backup_calls),
    )
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
    assert logic_manager.is_check_superseded(old_check, new_history) is True


def test_inspection_does_not_supersede_required_replacement():
    old_check = {"part_name": "Coolant", "action": "replace",
                 "last_service_date": "01-01-2026", "last_service_mileage": 10000}
    inspection = [{"part_name": "Coolant", "service_action": "inspect",
                   "service_date": "01-10-2026", "service_odometer": 20000}]
    assert logic_manager.is_check_superseded(old_check, inspection) is False


def test_urgent_menu_excludes_superseded_checks(monkeypatch):
    plate = "TEST123"
    saved = [{"license_plate": plate, "part_name": "Tyres", "action": "rotate",
              "outcome": "URGENT - overdue", "risk_score": 80,
              "last_service_date": "01-01-2026", "last_service_mileage": 10000}]
    history = [{"part_name": "Tyres", "service_action": "rotate",
                "service_date": "01-10-2026", "service_odometer": 30000}]
    output = []
    monkeypatch.setattr(data_manager, "query", lambda predicate: list(filter(predicate, saved)))
    monkeypatch.setattr(data_manager, "history_for_plate", lambda p: history)
    monkeypatch.setattr(io_manager, "display_list", lambda records: output.extend(records))
    monkeypatch.setattr(io_manager, "display_message", lambda message: output.append(message))
    main.urgent_flow({"license_plate": plate})
    assert not any(isinstance(item, dict) for item in output)
    assert "Nothing needs attention" in output[-1]


def test_history_crud_functions_required_by_main_are_available():
    # Protect against accidental removal of the maintenance-history data layer.
    names = ("load_history", "history_for_plate", "history_for_part",
             "add_service", "update_service", "delete_service", "delete_history_for_plate")
    for name in names:
        assert callable(getattr(data_manager, name))


def test_edited_or_deleted_service_invalidates_old_check():
    previous = {"part_name": "Engine Oil", "action": "replace", "service_id": 7,
                "last_service_date": "01-01-2026", "last_service_mileage": 10000,
                "last_service_action": "replace"}
    # Removing the referenced service makes the saved assessment outdated.
    assert logic_manager.is_check_superseded(previous, []) is True

    # Editing the same service ID also makes the old assessment outdated.
    edited = [{"service_id": 7, "part_name": "Engine Oil",
               "service_date": "02-01-2026", "service_odometer": 10000,
               "service_action": "replace"}]
    assert logic_manager.is_check_superseded(previous, edited) is True

    # An unchanged saved service must not hide a current warning.
    unchanged = [{"service_id": 7, "part_name": "Engine Oil",
                  "service_date": "01-01-2026", "service_odometer": 10000,
                  "service_action": "replace"}]
    assert logic_manager.is_check_superseded(previous, unchanged) is False
