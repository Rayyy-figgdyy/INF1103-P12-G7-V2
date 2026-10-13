"""
main.py -- entry point of the Car Maintenance & Service Risk Tracker.
Run it with: python main.py

Shows the menu, handles login and profile CRUD, and runs each part check through
the pipeline:  io_manager -> ai_manager -> logic_manager -> data_manager.
main.py is the only file that talks to all four managers; they never call each other.
Procedural only (C1: no classes); the logged-in user lives in main() as current_user.

See explanations/main_explained.txt for a full walkthrough.
"""

import datetime
import logging

import ai_manager
import data_manager
import io_manager
import logic_manager


# ======================================================================
# THE PIPELINE: one maintenance check, from start to finish
# ======================================================================

def build_record(raw_record: dict, manual_path: str | None = None) -> dict:
    """Run one check through the AI, then our business rules.
    Returns the finished record with facts, risk_score and outcome added."""
    # C2: every check goes through the AI. If no AI answers, ai_manager fills in
    # "AI unavailable" values, so route() later gives NEEDS MANUAL REVIEW.
    enriched = ai_manager.process(raw_record, manual_path=manual_path)

    # Add our own facts: km/days since service, overdue flags, service-by date.
    final_record = dict(enriched)
    final_record.update(logic_manager.evaluate(enriched))

    # score() is only used to sort the urgent list; route() makes the decision.
    final_record["risk_score"] = logic_manager.score(final_record)
    final_record["outcome"] = logic_manager.route(final_record)
    return final_record


def check_part_flow(user: dict) -> None:
    """Menu option 1: check one part of the logged-in user's car.
    Saves and shows the result (or the earlier answer for repeated inputs)."""
    car_model = user["car_model"]

    # The AI needs this car's manual PDF; stop early rather than crash without it.
    manual_path = data_manager.get_manual_path(car_model)
    if manual_path is None:
        io_manager.display_message(f"The manual for {car_model} is missing, so parts can't be checked.")
        return

    # Business rule 2: intervals must come from the stored schedule (cars.json).
    parts = data_manager.list_parts(car_model)
    if not parts:
        io_manager.display_message("No service schedule is available, so parts can't be checked.")
        return

    part_name = io_manager.prompt_part_choice(parts)
    interval = data_manager.get_service_interval(car_model, part_name)
    if interval is None:
        io_manager.display_message(f"No stored service interval for {part_name}.")
        return

    # Business rule 1: the new odometer reading can't go backwards. main.py looks up
    # the last reading because io_manager is not allowed to read the data files.
    last_odometer = data_manager.get_last_odometer(data_manager.load(), user["license_plate"])
    details = io_manager.prompt_service_details(last_odometer)

    raw_record = {
        "license_plate": user["license_plate"],
        "car_model": car_model,
        "car_condition": user["car_condition"],
        "coe_expiry_date": user["coe_expiry_date"],
        "part_name": part_name,
        "check_date": datetime.date.today().strftime("%d-%m-%Y"),   # stored as DD-MM-YYYY
    }
    raw_record.update(details)    # last service date and km, current odometer
    raw_record.update(interval)   # interval_km, interval_months

    # Same plate, part, service date, service km and current km as before? Reuse
    # the saved answer instead of calling the AI again (saves API calls, same result).
    previous = data_manager.find_repeat(raw_record)
    if previous is not None:
        io_manager.display_repeated(previous)
        return

    io_manager.display_message("\nAsking the AI to check this part against your manual...")
    final_record = build_record(raw_record, manual_path)

    # A failed save is warned about, but the result is still shown.
    saved_ok = data_manager.save(final_record)
    if not saved_ok:
        io_manager.display_message("Warning: the assessment could not be saved to disk.")
    io_manager.display_result(final_record)


