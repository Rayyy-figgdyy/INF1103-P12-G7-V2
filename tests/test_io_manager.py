"""
Regression tests for io_manager's display functions: a damaged or
old-format record in the data file must never crash the history screen.
"""
import io_manager

DAMAGED_RECORDS = [
    {"part_name": "Tyres", "current_odometer": "52000", "urgency_score": None,
     "outcome": "NEEDS MANUAL REVIEW"},                         # odometer saved as text
    {"part_name": "Engine Oil", "outcome": "OK - Not urgent"},  # most fields missing
    {"part_name": "Coolant", "current_odometer": None, "check_date": "not a date"},
]


def test_history_list_survives_damaged_records():
    io_manager.display_list(DAMAGED_RECORDS)  # must not raise


def test_assessment_screen_survives_missing_fields():
    io_manager.display_record({"part_name": "Battery", "is_overdue": True})  # must not raise


def test_km_formatting():
    assert io_manager.km(49000) == "49,000"
    assert io_manager.km("52000") == "52,000"
    assert io_manager.km(None) == "-"
    assert io_manager.km("lots") == "lots"


def test_date_formatting():
    assert io_manager.show_date("09-10-2026") == "09-10-2026"
    assert io_manager.show_date(None) == "-"
    assert io_manager.show_date("not a date") == "not a date"

def test_history_table_survives_damaged_entries():
    io_manager.display_history([
        {"part_name": "Coolant", "service_date": "not a date", "service_odometer": "abc"},
        {"part_name": None, "latest_check": {"urgency_score": None, "outcome": None}},
    ])  # must not raise


def test_multi_choice_accepts_several_parts_and_reasks_on_bad_input():
    import builtins
    answers = iter(["9", "4,6", ])                  # 9 is out of range, so it asks again
    saved_input = builtins.input
    builtins.input = lambda prompt="": next(answers)
    try:
        parts = ["Brake Pads", "Coolant", "Engine Air Filter", "Engine Oil", "Spark Plugs", "Tyres"]
        assert io_manager.prompt_multi_choice("Part numbers", parts) == ["Engine Oil", "Tyres"]
    finally:
        builtins.input = saved_input


def test_multi_choice_counts_a_repeated_number_once():
    import builtins
    answers = iter(["4 4 1"])
    saved_input = builtins.input
    builtins.input = lambda prompt="": next(answers)
    try:
        assert io_manager.prompt_multi_choice("Part numbers", ["A", "B", "C", "D"]) == ["D", "A"]
    finally:
        builtins.input = saved_input


def test_service_date_cannot_be_before_the_model_year_or_in_the_future():
    import datetime
    start_2020 = datetime.date(2020, 1, 1)
    assert io_manager.date_problem(datetime.date(2019, 12, 31), start_2020) is not None
    assert io_manager.date_problem(datetime.date(2020, 1, 1), start_2020) is None
    assert io_manager.date_problem(datetime.date.today() + datetime.timedelta(days=1), None) is not None
