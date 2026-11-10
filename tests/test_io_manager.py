"""
Tests for IOManager: a damaged or old-format record in the data file must never
crash the history screen, the input rules re-prompt correctly, and the account
screens work with UserProfile objects.
"""
import datetime

from io_manager import IOManager
from models.user_profile import UserProfile

DAMAGED_RECORDS = [
    {"part_name": "Tyres", "current_odometer": "52000", "urgency_score": None,
     "outcome": "NEEDS MANUAL REVIEW"},                         # odometer saved as text
    {"part_name": "Engine Oil", "outcome": "OK - Not urgent"},  # most fields missing
    {"part_name": "Coolant", "current_odometer": None, "check_date": "not a date"},
]


def make_user():
    return UserProfile("Darren", "SBA1234A", "Honda City 2025", "Brand New", "12-10-2030")


def test_history_list_survives_damaged_records():
    IOManager().display_list(DAMAGED_RECORDS)  # must not raise


def test_assessment_screen_survives_missing_fields():
    IOManager().display_record({"part_name": "Battery", "is_overdue": True})  # must not raise


def test_km_formatting():
    assert IOManager.km(49000) == "49,000"
    assert IOManager.km("52000") == "52,000"
    assert IOManager.km(None) == "-"
    assert IOManager.km("lots") == "lots"


def test_date_formatting():
    assert IOManager.show_date("09-10-2026") == "09-10-2026"
    assert IOManager.show_date(None) == "-"
    assert IOManager.show_date("not a date") == "not a date"


def test_multi_choice_accepts_several_parts_and_reasks_on_bad_input(monkeypatch):
    answers = iter(["9", "4,6"])                  # 9 is out of range, so it asks again
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    parts = ["Brake Pads", "Coolant", "Engine Air Filter", "Engine Oil", "Spark Plugs", "Tyres"]
    assert IOManager().prompt_multi_choice("Part numbers", parts) == ["Engine Oil", "Tyres"]


def test_service_date_cannot_be_before_the_model_year_or_in_the_future():
    start_2020 = datetime.date(2020, 1, 1)
    assert IOManager.date_problem(datetime.date(2019, 12, 31), start_2020) is not None
    assert IOManager.date_problem(datetime.date(2020, 1, 1), start_2020) is None
    assert IOManager.date_problem(datetime.date.today() + datetime.timedelta(days=1), None) is not None


def test_coe_must_be_between_model_year_and_ten_years_ahead():
    earliest, latest = datetime.date(2020, 1, 1), datetime.date(2036, 10, 13)
    assert IOManager.coe_problem(datetime.date(2015, 1, 1), earliest, latest) is not None
    assert IOManager.coe_problem(datetime.date(2099, 1, 1), earliest, latest) is not None
    assert IOManager.coe_problem(datetime.date(2025, 1, 1), earliest, latest) is None  # expired is allowed


def test_schedule_text_leaves_out_a_missing_limit():
    assert IOManager.schedule_text({"interval_km": 10000, "interval_months": 12}) == "every 10,000 km or 12 months"
    assert IOManager.schedule_text({"interval_km": 100000, "interval_months": 0}) == "every 100,000 km (no time limit)"
    assert IOManager.schedule_text({"interval_km": 0, "interval_months": 12}) == "every 12 months (no km limit)"


def test_schedule_text_shows_the_manual_action_and_stage():
    assert IOManager.schedule_text({"interval_km": 16000, "interval_months": 12, "action": "inspect"}) \
        == "inspect every 16,000 km or 12 months"
    assert IOManager.schedule_text({"interval_km": 40000, "interval_months": 24, "action": "replace",
                                    "interval_stage": "repeat"}) \
        == "replace every 40,000 km or 24 months (after the first change)"


def test_service_action_allows_rotate_only_for_tyres(monkeypatch):
    replies = iter(["2", "3"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(replies))
    io = IOManager()
    assert io.prompt_service_action("Brake Pads") == "replace"
    assert io.prompt_service_action("Tyres") == "rotate"


def test_display_record_shows_combined_brake_history_pattern(capsys):
    record = {
        "part_name": "Brake Pads", "car_model": "Honda City 2025",
        "license_plate": "SBA1234A", "urgency_score": 7, "confidence": "High",
        "history_context": {"eligible": True, "replacement_count": 3, "reason": ""},
        "history_pattern": "Previous replacements were about 20,000 km apart.",
    }
    IOManager().display_record(record)
    shown = capsys.readouterr().out
    assert "History used:       yes" in shown
    assert "about 20,000 km apart" in shown


# ---- new OOP behaviour: account screens take UserProfile objects

def test_main_menu_shows_the_logged_in_user_profile(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": " 7 ")
    assert IOManager().prompt_main_menu(make_user()) == "7"
    shown = capsys.readouterr().out
    assert "Logged in: Darren | SBA1234A | Honda City 2025" in shown


def test_main_menu_logged_out(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    assert IOManager().prompt_main_menu(None) == "1"
    assert "Not logged in" in capsys.readouterr().out


def test_display_user_prints_profile_attributes(capsys):
    IOManager().display_user(make_user())
    shown = capsys.readouterr().out
    assert "Name:            Darren" in shown
    assert "License plate:   SBA1234A" in shown
    assert "Car condition:   Brand New" in shown
    assert "COE expiry date: 12-10-2030" in shown


def test_updated_profile_is_a_copy_and_original_is_unchanged(monkeypatch):
    # "Dan" = new name; "99-99-2030" is not a real date, so it re-asks; then a valid COE.
    replies = iter(["Dan", "99-99-2030", "01-06-2031"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(replies))
    original = make_user()
    updated = IOManager().prompt_updated_profile(original, datetime.date(2025, 1, 1),
                                                 datetime.date(2035, 1, 1))
    assert isinstance(updated, UserProfile) and updated is not original
    assert updated.name == "Dan" and updated.coe_expiry_date == "01-06-2031"
    assert updated.license_plate == "SBA1234A"
    assert original.name == "Darren" and original.coe_expiry_date == "12-10-2030"


def test_updated_profile_enter_keeps_old_values(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    updated = IOManager().prompt_updated_profile(make_user())
    assert updated.to_dict() == make_user().to_dict()
