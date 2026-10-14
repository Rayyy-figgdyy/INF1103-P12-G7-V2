# Test manufacturer intervals, service actions and urgency decisions.
"""
Tests for logic_manager using hardcoded sample AI responses -- no live
API connection (framework brief 5.3). Run with:  python -m pytest
"""
import logic_manager

CHECK_DATE = "01-10-2026"


def sample_record(**overrides) -> dict:
    """An AI-enriched record as it arrives from ai_manager.process().
    Engine oil, schedule 10,000 km / 6 months (= 183 days), last serviced
    92 days before CHECK_DATE, 4,600 km ago (50 km per day)."""
    record = {
        "license_plate": "SBA1234A",
        "car_model": "Toyota Corolla 2020",
        "car_condition": "Used",
        "coe_expiry_date": "01-01-2030",
        "part_name": "Engine Oil",
        "interval_km": 10_000,
        "interval_months": 6,
        "last_service_date": "01-07-2026",
        "last_service_mileage": 40_000,
        "current_odometer": 44_600,
        "check_date": CHECK_DATE,
        # hardcoded sample AI response fields:
        "urgency_score": 2,
        "confidence": "High",
        "overdue_summary": "Engine oil: 5,400 km remaining",
        "recommended_action": "No action needed yet.",
        "ai_status": "ok",
    }
    record.update(overrides)
    return record


# --- evaluate() -------------------------------------------------------------

def test_evaluate_not_overdue():
    d = logic_manager.evaluate(sample_record())
    assert d["km_since_service"] == 4_600
    assert d["days_since_service"] == 92
    assert d["is_overdue"] is False
    assert d["km_overdue"] == 0 and d["days_overdue"] == 0
    assert d["km_per_day"] == 50.0


def test_evaluate_overdue_by_distance():
    d = logic_manager.evaluate(sample_record(current_odometer=50_650))  # 10,650 km since service
    assert d["is_overdue"] is True
    assert d["km_overdue"] == 650


def test_evaluate_overdue_by_time_only():
    # 1 year since service but very little driving: overdue by time, not distance.
    d = logic_manager.evaluate(sample_record(last_service_date="01-10-2025", current_odometer=41_000))
    assert d["is_overdue"] is True
    assert d["km_overdue"] == 0
    assert d["days_overdue"] == 365 - 183


def test_evaluate_does_not_modify_input():
    record = sample_record()
    before = dict(record)
    logic_manager.evaluate(record)
    assert record == before


def test_evaluate_flags_safety_critical_parts():
    assert logic_manager.evaluate(sample_record(part_name="Brake Pads"))["is_safety_critical"] is True
    assert logic_manager.evaluate(sample_record(part_name="Air Filter"))["is_safety_critical"] is False


# --- Business rule 3: recommended service date -------------------------------

def test_service_date_from_schedule_when_low_urgency():
    # Due by time in 91 days (31-12-2026); by distance at 50 km/day in 108 days.
    # The earlier one wins; urgency 2 doesn't pull it forward.
    d = logic_manager.evaluate(sample_record())
    assert d["recommended_service_date"] == "31-12-2026"


def test_service_date_today_when_overdue():
    d = logic_manager.evaluate(sample_record(current_odometer=55_000))
    assert d["recommended_service_date"] == CHECK_DATE


def test_high_ai_urgency_pulls_service_date_forward():
    d = logic_manager.evaluate(sample_record(urgency_score=9))
    assert d["recommended_service_date"] == "04-10-2026"  # within 3 days


def test_safety_critical_halves_the_urgency_window():
    d = logic_manager.evaluate(sample_record(urgency_score=6, part_name="Brake Pads"))
    assert d["recommended_service_date"] == "08-10-2026"  # 14 days halved to 7


# --- score() -------------------------------------------------------------------

def test_score_rises_when_overdue():
    on_time = logic_manager.score(sample_record(urgency_score=5))
    overdue = logic_manager.score(sample_record(urgency_score=5, current_odometer=55_000))
    assert overdue == on_time + 15


def test_score_is_capped_at_100():
    record = sample_record(urgency_score=10, part_name="Brake Pads", current_odometer=99_000)
    assert logic_manager.score(record) == 100


def test_score_zero_when_ai_unavailable():
    assert logic_manager.score(sample_record(urgency_score=None, ai_status="unavailable")) == 0


# --- route(): multi-condition rules -----------------------------------------------

def test_route_urgent_needs_high_score_and_high_confidence():
    assert logic_manager.route(sample_record(urgency_score=9, confidence="High")) == "URGENT - Service immediately"


def test_route_same_score_low_confidence_is_flagged_not_urgent():
    # Same urgency as above, only confidence differs -> different outcome.
    # Proves the rule depends on BOTH AI fields.
    assert logic_manager.route(sample_record(urgency_score=9, confidence="Low")).startswith("FLAGGED")


def test_route_safety_critical_overdue_is_urgent_even_at_moderate_score():
    record = sample_record(part_name="Brake Pads", urgency_score=6, current_odometer=85_000)
    assert logic_manager.route(record) == "URGENT - Safety-critical part overdue"


def test_route_coe_expired():
    assert logic_manager.route(sample_record(coe_expiry_date="01-09-2026")).startswith("COE EXPIRED")


def test_route_defer_when_coe_expiring_and_non_critical_and_low_urgency():
    record = sample_record(coe_expiry_date="15-01-2027", urgency_score=3)
    assert logic_manager.route(record).startswith("DEFER")


def test_route_no_defer_for_safety_critical_part_even_if_coe_expiring():
    record = sample_record(coe_expiry_date="15-01-2027", urgency_score=3, part_name="Tyres")
    assert not logic_manager.route(record).startswith("DEFER")


def test_route_due_soon_when_overdue():
    assert logic_manager.route(sample_record(urgency_score=6, current_odometer=55_000)).startswith("DUE SOON")


def test_route_ok_when_low_urgency_and_on_schedule():
    assert logic_manager.route(sample_record(urgency_score=2)) == "OK - Not urgent"


def test_route_monitor_for_middle_urgency():
    assert logic_manager.route(sample_record(urgency_score=5)).startswith("MONITOR")


def test_route_manual_review_when_ai_unavailable():
    record = sample_record(urgency_score=None, confidence="Unknown", ai_status="unavailable")
    assert logic_manager.route(record).startswith("NEEDS MANUAL REVIEW")


def test_is_urgent():
    assert logic_manager.is_urgent({"outcome": "URGENT - Service immediately"}) is True
    assert logic_manager.is_urgent({"outcome": "OK - Not urgent"}) is False
    assert logic_manager.is_urgent({}) is False
    # The AI couldn't assess it, so the owner still needs to act.
    assert logic_manager.is_urgent({"outcome": "NEEDS MANUAL REVIEW - AI assessment unavailable"}) is True


# --- Maintenance history rules ------------------------------------------------------

HISTORY = [
    {"service_id": 1, "part_name": "Engine Oil", "service_date": "20-03-2025", "service_odometer": 48_000},
    {"service_id": 2, "part_name": "Engine Oil", "service_date": "20-03-2026", "service_odometer": 58_000},
    {"service_id": 3, "part_name": "Coolant", "service_date": "18-09-2021", "service_odometer": 25_000},
]


def test_latest_service_picks_the_newest_of_that_part():
    assert logic_manager.latest_service(HISTORY, "Engine Oil")["service_id"] == 2
    assert logic_manager.latest_service(HISTORY, "Tyres") is None


def test_sort_history_is_newest_first():
    ids = [e["service_id"] for e in logic_manager.sort_history(HISTORY)]
    assert ids == [2, 1, 3]


def test_odometer_must_go_up_over_time():
    # A later date with fewer km than an earlier service is refused...
    assert logic_manager.check_service_odometer(HISTORY, "01-06-2026", 50_000) is not None
    # ...and so is an earlier date with more km than a later service.
    assert logic_manager.check_service_odometer(HISTORY, "01-01-2022", 60_000) is not None
    # A reading that fits between the others is fine.
    assert logic_manager.check_service_odometer(HISTORY, "01-06-2026", 60_000) is None


def test_odometer_check_ignores_the_entry_being_edited():
    assert logic_manager.check_service_odometer(HISTORY, "20-03-2026", 57_000) is None
    assert logic_manager.check_service_odometer(HISTORY, "21-03-2026", 57_000) is not None
    assert logic_manager.check_service_odometer(HISTORY, "21-03-2026", 57_000, ignore_id=2) is None


def test_only_the_newest_check_per_part_counts():
    checks = [{"part_name": "Engine Oil", "outcome": "URGENT - Service immediately"},
              {"part_name": "Coolant", "outcome": "OK - Not urgent"},
              {"part_name": "Engine Oil", "outcome": "OK - Not urgent"}]
    latest = logic_manager.latest_check_per_part(checks)
    assert len(latest) == 2
    assert not any(logic_manager.is_urgent(r) for r in latest)


def test_latest_check_is_matched_to_its_service():
    checks = [{"part_name": "Engine Oil", "last_service_date": "20-03-2026",
               "last_service_mileage": 58_000, "urgency_score": 8},
              {"part_name": "Engine Oil", "last_service_date": "20-03-2025",
               "last_service_mileage": 48_000, "urgency_score": 3}]
    assert logic_manager.latest_check_for_service(checks, HISTORY[1])["urgency_score"] == 8
    assert logic_manager.latest_check_for_service(checks, HISTORY[2]) is None


# --- Plausibility rules: distances, COE range, duplicates ----------------------------

import datetime


def test_more_than_2000_km_a_day_is_refused():
    assert logic_manager.km_pace_problem("01-06-2026", 63_000, "13-10-2026", 1_999_999) is not None
    assert logic_manager.km_pace_problem("01-06-2026", 63_000, "13-10-2026", 69_800) is None
    # Same day counts as one day: up to 2,000 km is still believable, 2,001 is not.
    assert logic_manager.km_pace_problem("01-06-2026", 63_000, "01-06-2026", 65_000) is None
    assert logic_manager.km_pace_problem("01-06-2026", 63_000, "01-06-2026", 65_001) is not None


def test_service_km_must_be_reachable_since_the_model_year():
    # A 2025 car can't have done 300,000 km by May 2025 (124 days x 2,000 = 248,000 max).
    assert logic_manager.check_service_pace([], "05-05-2025", 300_000, 2025) is not None
    assert logic_manager.check_service_pace([], "05-05-2025", 10_000, 2025) is None


def test_service_km_must_be_reachable_from_other_services():
    history = [{"service_id": 1, "part_name": "Tyres", "service_date": "01-06-2026",
                "service_odometer": 63_000}]
    assert logic_manager.check_service_pace(history, "03-06-2026", 70_000, 2020) is not None
    assert logic_manager.check_service_pace(history, "03-06-2026", 64_000, 2020) is None
    # The entry being edited is not compared with itself.
    assert logic_manager.check_service_pace(history, "03-06-2026", 70_000, 2020, ignore_id=1) is None


def test_highest_believable_reading_today():
    history = [{"service_date": "01-06-2026", "service_odometer": 63_000}]
    checks = [{"check_date": "12-10-2026", "current_odometer": 69_500}]
    assert logic_manager.latest_reading(history, checks) == ("12-10-2026", 69_500)
    assert logic_manager.max_plausible_odometer("12-10-2026", 69_500,
                                                datetime.date(2026, 10, 13)) == 71_500


def test_coe_range_is_model_year_to_ten_years_ahead():
    earliest, latest = logic_manager.coe_date_range(2020, datetime.date(2026, 10, 13))
    assert earliest == datetime.date(2020, 1, 1)
    assert latest == datetime.date(2036, 10, 13)
    # 29 Feb + 10 years falls back to 28 Feb.
    assert logic_manager.coe_date_range(None, datetime.date(2028, 2, 29)) == (None, datetime.date(2038, 2, 28))


def test_exact_duplicate_service_is_found():
    history = [{"service_id": 1, "part_name": "Engine Oil", "service_date": "20-03-2026",
                "service_odometer": 58_000}]
    assert logic_manager.find_duplicate_service(history, "Engine Oil", "20-03-2026", 58_000) is not None
    assert logic_manager.find_duplicate_service(history, "Tyres", "20-03-2026", 58_000) is None
    assert logic_manager.find_duplicate_service(history, "Engine Oil", "20-03-2026", 58_000, ignore_id=1) is None


def test_a_zero_limit_means_no_limit_of_that_kind():
    # Spark plugs every 100,000 km with no time limit: 5 years later but few km = not overdue.
    no_time = logic_manager.evaluate(sample_record(interval_km=100_000, interval_months=0,
                                                   last_service_date="01-10-2021"))
    assert no_time["is_overdue"] is False
    # Honda oil: every 12 months, no km limit: a huge distance alone is not overdue...
    no_km = logic_manager.evaluate(sample_record(interval_km=0, interval_months=12,
                                                 current_odometer=90_000))
    assert no_km["is_overdue"] is False
    # ...but more than a year is.
    assert logic_manager.evaluate(sample_record(interval_km=0, interval_months=12,
                                                last_service_date="01-09-2025"))["is_overdue"] is True


# --- Manual actions and 'first at X, then every Y' rules ---------------------------

COOLANT_RULE = {"interval_km": 200_000, "interval_months": 120, "action": "replace",
                "repeat_km": 40_000, "repeat_months": 24}


def test_first_interval_until_the_part_has_been_replaced():
    first = logic_manager.choose_interval(COOLANT_RULE, [])
    assert (first["interval_km"], first["interval_months"], first["interval_stage"]) == (200_000, 120, "first")
    repeat = logic_manager.choose_interval(COOLANT_RULE, [{"part_name": "Coolant", "service_action": "replace"}])
    assert (repeat["interval_km"], repeat["interval_months"], repeat["interval_stage"]) == (40_000, 24, "repeat")


def test_single_interval_rule_has_no_stage():
    rule = {"interval_km": 15_000, "interval_months": 12, "action": "inspect"}
    chosen = logic_manager.choose_interval(rule, [{"part_name": "Brake Pads"}])
    assert chosen == {"interval_km": 15_000, "interval_months": 12, "action": "inspect", "interval_stage": None}


def test_from_new_starts_at_zero_km_on_1_january_of_the_model_year():
    entry = logic_manager.from_new_service("Coolant", 2021)
    assert (entry["service_date"], entry["service_odometer"]) == ("01-01-2021", 0)


def test_overdue_safety_inspection_is_worded_as_an_inspection():
    record = sample_record(part_name="Brake Pads", action="inspect", urgency_score=3,
                           last_service_date="01-10-2025")
    assert logic_manager.route(record) == "URGENT - Safety-critical inspection overdue"
    record = sample_record(part_name="Tyres", action="rotate", urgency_score=3,
                           last_service_date="01-10-2025")
    assert logic_manager.route(record) == "URGENT - Safety-critical tyre rotation overdue"


def test_service_action_keeps_inspection_and_replacement_separate():
    entries = [{"part_name": "Brake Pads", "service_date": "01-01-2026",
                "service_odometer": 50000, "service_action": "inspect"}]
    assert logic_manager.find_duplicate_service(
        entries, "Brake Pads", "01-01-2026", 50000, service_action="replace"
    ) is None


def test_brake_history_requires_enough_valid_replacements():
    entries = [
        {"part_name": "Brake Pads", "service_action": "replace", "service_date": date,
         "service_odometer": km}
        for date, km in (("01-01-2022", 20000), ("01-01-2024", 40000), ("01-01-2026", 60000))
    ]
    context = logic_manager.brake_history_context(entries, 2020, datetime.date(2026, 10, 14), 70000)
    assert context["eligible"] is True and context["replacement_count"] == 3
    assert [item["service_odometer"] for item in context["replacement_records"]] == [20000, 40000, 60000]
    too_short = logic_manager.brake_history_context(entries[:2], 2020, datetime.date(2026, 10, 14), 70000)
    assert too_short["eligible"] is False
    invalid = logic_manager.brake_history_context(
        [{**entries[0], "service_odometer": 90000}], 2020, datetime.date(2026, 10, 14), 70000
    )
    assert invalid["eligible"] is False and invalid["reason"]

def test_combined_brake_urgency_uses_the_normal_score_and_route_pipeline():
    record = sample_record(part_name="Brake Pads", urgency_score=8, confidence="High",
                           current_odometer=49_000)
    assert logic_manager.score(record) >= 80
    assert logic_manager.route(record) == "URGENT - Service immediately"



def test_inspection_and_unknown_actions_keep_first_interval():
    # Only a confirmed replacement activates the shorter repeat interval.
    for action in ("inspect", "unknown", None):
        history = [{"part_name": "Coolant", "service_action": action}]
        result = logic_manager.choose_interval(COOLANT_RULE, history)
        assert result["interval_stage"] == "first"
        assert result["interval_km"] == 200_000


def test_unknown_history_does_not_reset_replacement_schedule():
    # An old entry with no action should not be mistaken for a coolant change.
    history = [
        {"part_name": "Coolant", "service_date": "01-01-2024",
         "service_odometer": 20_000, "service_action": "unknown"},
        {"part_name": "Coolant", "service_date": "01-01-2025",
         "service_odometer": 40_000, "service_action": "replace"},
    ]
    last = logic_manager.latest_service(history, "Coolant", "replace")
    assert last["service_odometer"] == 40_000
    assert logic_manager.latest_service(history[:1], "Coolant", "replace") is None
