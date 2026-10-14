"""
main.py -- entry point of the Car Maintenance & Service Risk Tracker.
Run it with: python main.py

Shows the menu, handles login, profile CRUD and maintenance history CRUD, and runs
each urgency check through the pipeline:
    io_manager -> ai_manager -> logic_manager -> data_manager.
An urgency check is based on the latest service of that part in the owner's
maintenance history; identical checks are answered from prompt_records.json.
main.py is the only file that talks to all four managers; they never call each other.
Procedural only (C1: no classes); the logged-in user lives in main() as current_user.

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
    # C2: every check goes through the AI. Eligible Brake Pad history is combined with
    # the manual inside this one AI assessment, producing one urgency_score.
    enriched = ai_manager.process(raw_record, manual_path=manual_path)

    # Add our own facts: km/days since service, overdue flags, service-by date.
    final_record = dict(enriched)
    final_record.update(logic_manager.evaluate(enriched))

    # score() is only used to sort the urgent list; route() makes the decision.
    final_record["risk_score"] = logic_manager.score(final_record)
    final_record["outcome"] = logic_manager.route(final_record)
    return final_record


def earliest_service_date(user: dict) -> datetime.date | None:
    """Return 1 January of the car's model year (e.g. 01-01-2020 for a 2020 model):
    no service can be dated before the car was made. None if the year is unknown."""
    year = data_manager.get_model_year(user["car_model"])
    if year is None:
        return None
    return datetime.date(year, 1, 1)


def service_problem(user: dict, entries: list[dict], service_date: str, odometer: int,
                    ignore_id: int | None = None) -> str | None:
    """Run the history rules on one service: the odometer can't go backwards
    (business rule 1) and can't grow faster than logic_manager.MAX_KM_PER_DAY.
    Returns the first problem found, or None if the service fits."""
    model_year = data_manager.get_model_year(user["car_model"])
    return (logic_manager.check_service_odometer(entries, service_date, odometer, ignore_id)
            or logic_manager.check_service_pace(entries, service_date, odometer,
                                                model_year, ignore_id))


def coe_limits(car_model: str) -> tuple:
    """The allowed COE expiry range for this car: (earliest, latest) dates."""
    return logic_manager.coe_date_range(data_manager.get_model_year(car_model),
                                        datetime.date.today())


def last_odometer_on_file(license_plate: str) -> int | None:
    """Return the highest odometer reading saved for this car, from its AI checks
    and its maintenance history together, or None if there is none."""
    all_saved = data_manager.load() + data_manager.load_history()
    return data_manager.get_last_odometer(all_saved, license_plate)


# ======================================================================
# MAINTENANCE HISTORY: Create, Read, Update, Delete ("CRUD")
# ======================================================================

# Ask for an invoice until its date and mileage fit the saved history.
def prompt_valid_invoice(user: dict, history: list[dict], parts: list[str],
                         part_name: str | None = None) -> dict | None:
    while True:
        invoice = io_manager.prompt_service_entry(
            parts, part_name, earliest_service_date(user)
        )
        problem = service_problem(
            user, history, invoice["service_date"], invoice["service_odometer"]
        )

        if problem is None:
            return invoice

        io_manager.display_message(f"  -> {problem}")
        if not io_manager.confirm_action("Enter this invoice again?"):
            return None


# Save one part from an invoice and return the saved entry.
def save_invoice_part(user: dict, history: list[dict], invoice: dict,
                      part_name: str) -> dict | None:
    service_action = invoice["service_actions"][part_name]

    duplicate = logic_manager.find_duplicate_service(
        history,
        part_name,
        invoice["service_date"],
        invoice["service_odometer"],
        service_action=service_action,
    )
    if duplicate is not None:
        io_manager.display_message(
            f"  -> {part_name} on {invoice['service_date']} at "
            f"{invoice['service_odometer']:,} km is already in your history, "
            "so it was not added again."
        )
        return None

    entry = {
        "license_plate": user["license_plate"],
        "part_name": part_name,
        "service_action": service_action,
        "service_date": invoice["service_date"],
        "service_odometer": invoice["service_odometer"],
        "notes": invoice["notes"],
    }

    saved = data_manager.add_service(entry)
    if saved is None:
        io_manager.display_message(
            f"Could not save the {part_name} service. Please try again."
        )
    return saved


# Ask for one invoice and save one history entry for each serviced part.
def save_new_services(user: dict, part_name: str | None = None) -> list[dict]:
    parts = data_manager.list_parts(user["car_model"])
    if not parts:
        io_manager.display_message("No service schedule is available for your car.")
        return []

    history = data_manager.history_for_plate(user["license_plate"])
    invoice = prompt_valid_invoice(user, history, parts, part_name)
    if invoice is None:
        return []

    saved_entries = []
    for name in invoice["part_names"]:
        saved = save_invoice_part(user, history, invoice, name)
        if saved is not None:
            saved_entries.append(saved)

    if saved_entries:
        io_manager.display_message(
            f"\n{len(saved_entries)} service(s) added to your history:"
        )
        for saved in saved_entries:
            io_manager.display_service(saved)

    return saved_entries


# Menu option 1: add an invoice to the car's maintenance history.
def add_service_flow(user: dict) -> None:
    save_new_services(user)


# Menu option 2: show services newest first with their latest assessments.
def history_flow(user: dict) -> None:
    plate = user["license_plate"]
    entries = logic_manager.sort_history(data_manager.history_for_plate(plate))

    if not entries:
        io_manager.display_message(
            f"\nNo services in the history for {plate} yet. "
            "Choose 1 to add the services you've had done."
        )
        return

    saved_checks = data_manager.query(
        lambda record: record.get("license_plate") == plate
    )

    rows = []
    for entry in entries:
        row = dict(entry)  # Copy it so the saved entry is not changed.
        row["latest_check"] = logic_manager.latest_check_for_service(
            saved_checks, entry
        )
        rows.append(row)

    io_manager.display_history(rows)


# Check whether an edited service conflicts with saved history.
def edited_service_problem(user: dict, entries: list[dict], chosen: dict,
                           updated: dict) -> str | None:
    problem = service_problem(
        user,
        entries,
        updated["service_date"],
        updated["service_odometer"],
        chosen.get("service_id"),
    )
    if problem is not None:
        return problem

    duplicate = logic_manager.find_duplicate_service(
        entries,
        updated["part_name"],
        updated["service_date"],
        updated["service_odometer"],
        chosen.get("service_id"),
        service_action=updated.get("service_action") or "unknown",
    )
    if duplicate is not None:
        return "That would be an exact copy of a service already in your history."

    return None


# Menu option 3: edit one saved service after validation.
def edit_service_flow(user: dict) -> None:
    entries = logic_manager.sort_history(
        data_manager.history_for_plate(user["license_plate"])
    )
    if not entries:
        io_manager.display_message(
            "\nYour history is empty, so there is nothing to edit."
        )
        return

    chosen = io_manager.prompt_service_choice(entries, "edit")
    if chosen is None:
        io_manager.display_message("Edit cancelled.")
        return

    parts = data_manager.list_parts(user["car_model"])
    updated = io_manager.prompt_updated_service(
        chosen, parts, earliest_service_date(user)
    )

    problem = edited_service_problem(user, entries, chosen, updated)
    if problem is not None:
        io_manager.display_message(f"  -> {problem}\nNothing was changed.")
        return

    if not data_manager.update_service(updated):
        io_manager.display_message("Could not save your changes. Please try again.")
        return

    io_manager.display_message("\nService updated:")
    io_manager.display_service(updated)


# Menu option 4: delete one saved service after confirmation.
def delete_service_flow(user: dict) -> None:
    entries = logic_manager.sort_history(
        data_manager.history_for_plate(user["license_plate"])
    )
    if not entries:
        io_manager.display_message(
            "\nYour history is empty, so there is nothing to delete."
        )
        return

    chosen = io_manager.prompt_service_choice(entries, "delete")
    if chosen is None:
        io_manager.display_message("Delete cancelled.")
        return

    io_manager.display_service(chosen)
    if not io_manager.confirm_action("Delete this service from your history?"):
        io_manager.display_message("Delete cancelled.")
        return

    if data_manager.delete_service(chosen.get("service_id")):
        io_manager.display_message("Service deleted.")
    else:
        io_manager.display_message("Could not delete the service. Please try again.")


# ======================================================================
# URGENCY CHECKS (AI) and the urgent list
# ======================================================================

def check_part_flow(user: dict) -> None:
    """Menu option 5: check one part, based on its latest service in the history.
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

    # The "last service" comes from the maintenance history, not from typing it again.
    history = data_manager.history_for_plate(user["license_plate"])
    model_year = data_manager.get_model_year(car_model)
    last_service = logic_manager.latest_service(
        history, part_name, interval.get("action", "replace"), model_year
    )
    from_new = False
    if last_service is None:
        io_manager.display_message(f"\nThere is no {part_name} service in your maintenance history yet.")
        # A part with a 'first at X, then every Y' rule (e.g. coolant) may never have
        # been replaced; then the first interval is counted from the car being new.
        if "repeat_km" in interval and model_year is not None:
            from_new = not io_manager.confirm_action(f"Has the {part_name} ever been replaced?")

        if from_new:
            last_service = logic_manager.from_new_service(part_name, model_year)
        else:
            if not io_manager.confirm_action(f"Add your last {part_name} service now?"):
                return
            new_entries = save_new_services(user, part_name)
            if not new_entries:
                return
            history = data_manager.history_for_plate(user["license_plate"])
            last_service = logic_manager.latest_service(
                history, part_name, interval.get("action", "replace"), model_year
            )
            if last_service is None:
                io_manager.display_message(
                    "The entry was saved, but an inspection does not reset this service interval. "
                    "Record the last replacement or rotation before checking this part."
                )
                return

    if from_new:
        io_manager.display_message(f"\nChecking your {part_name} from new "
                                   "(the manual's first-change interval applies):")
    else:
        io_manager.display_message(f"\nUsing your last {part_name} service from your history:")
    io_manager.display_service(last_service)

    # 'First at X, then every Y': once this part has been replaced, Y applies.
    part_services = [e for e in history if e.get("part_name") == part_name]
    chosen_interval = logic_manager.choose_interval(interval, part_services)

    # Business rule 1: the new odometer reading can't go backwards. main.py looks up
    # the last reading because io_manager is not allowed to read the data files.
    # Plausibility: no more than MAX_KM_PER_DAY since the latest reading on file.
    my_checks = data_manager.query(lambda r: r.get("license_plate") == user["license_plate"])
    latest = logic_manager.latest_reading(data_manager.history_for_plate(user["license_plate"]),
                                          my_checks)
    max_plausible = None
    if latest is not None:
        max_plausible = logic_manager.max_plausible_odometer(latest[0], latest[1],
                                                             datetime.date.today())
    current_odometer = io_manager.prompt_current_odometer(
        last_service["service_odometer"], last_odometer_on_file(user["license_plate"]),
        max_plausible)

    raw_record = {
        "license_plate": user["license_plate"],
        "car_model": car_model,
        "car_condition": user["car_condition"],
        "coe_expiry_date": user["coe_expiry_date"],
        "part_name": part_name,
        "check_date": datetime.date.today().strftime("%d-%m-%Y"),   # stored as DD-MM-YYYY
        "service_id": last_service.get("service_id"),
        "last_service_date": last_service["service_date"],
        "last_service_mileage": last_service["service_odometer"],
        "last_service_action": last_service.get("service_action") or "unknown",
        "current_odometer": current_odometer,
    }
    raw_record.update(chosen_interval)   # interval_km, interval_months, action, interval_stage

    # Brake Pads use personalised history only after Python verifies enough reliable replacements.
    if part_name == "Brake Pads":
        raw_history = data_manager.history_for_part(user["license_plate"], part_name)
        context = logic_manager.brake_history_context(
            raw_history, model_year, datetime.date.today(), current_odometer
        )
        raw_record["history_context"] = {
            "eligible": context["eligible"],
            "replacement_count": context["replacement_count"],
            "reason": context["reason"],
        }
        if context["eligible"]:
            # The AI gets the validated raw replacement points and calculates intervals itself.
            raw_record["brake_pad_history"] = context["replacement_records"]

    # Nothing new since a saved check (same plate, part, last service and current km)?
    # Show the saved answer instead of calling the AI again (saves API calls).
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


def urgent_flow(user: dict) -> None:
    """Menu option 6: list the parts that need attention, highest risk first.
    Only each part's newest check counts, so a re-checked part drops off the list."""
    my_checks = data_manager.query(lambda r: r.get("license_plate") == user["license_plate"])
    # is_urgent(): outcome starts with URGENT, FLAGGED, DUE SOON, COE EXPIRED
    # or NEEDS MANUAL REVIEW.
    urgent_records = []
    for record in logic_manager.latest_check_per_part(my_checks):
        if logic_manager.is_urgent(record):
            urgent_records.append(record)
    # Highest risk_score first; records without a score sort as 0.
    urgent_records.sort(key=lambda r: r.get("risk_score", 0), reverse=True)
    if not urgent_records:
        io_manager.display_message("\nNothing needs attention right now: none of your parts' latest "
                                   "checks are urgent, flagged, overdue or waiting for manual review. "
                                   "(Choose 2 to see your history.)")
        return
    io_manager.display_list(urgent_records)


# ======================================================================
# ACCOUNTS: log in, and Create / Read / Update / Delete a profile ("CRUD")
# ======================================================================

def login_flow() -> dict | None:
    """Log in by license plate.
    Returns the user's profile, or None if no profile has that plate."""
    plate = io_manager.prompt_login()
    user = data_manager.find_user_by_plate(plate)
    if user is None:
        io_manager.display_message(f"No profile for {plate}. Choose 'Register new profile' first.")
        return None
    io_manager.display_message(f"\nWelcome back, {user['name']}!")
    return user


def register_flow() -> dict | None:
    """CREATE a new profile and log the user in.
    Returns the new profile, or None if the car list is missing or saving failed."""
    car_models = data_manager.list_car_models()
    if not car_models:
        io_manager.display_message("The car list (data/cars.json) is missing, so you can't register yet.")
        return None

    # The license plate is the account ID, so io_manager must refuse duplicates.
    taken_plates = {u.get("license_plate") for u in data_manager.load_users()}

    identity = io_manager.prompt_identity(taken_plates)
    car_model = io_manager.prompt_car_choice(car_models)

    profile = {
        "name": identity["name"],
        "license_plate": identity["license_plate"],
        "car_model": car_model,
        # Brand New / Used comes from cars.json, not from the user.
        "car_condition": data_manager.find_car(car_model)["condition"],
        "coe_expiry_date": io_manager.prompt_coe_expiry(*coe_limits(car_model)),
    }

    if not data_manager.save_user(profile):
        io_manager.display_message("Could not save your profile. Please try again.")
        return None
    io_manager.display_message("\nProfile created -- you are now logged in.")
    io_manager.display_user(profile)
    return profile


def update_profile_flow(user: dict) -> dict:
    """UPDATE the user's name or COE expiry date (plate and car are fixed).
    Returns the updated profile, or the unchanged one if saving failed."""
    updated = io_manager.prompt_updated_profile(user, *coe_limits(user["car_model"]))
    if not data_manager.save_user(updated):
        io_manager.display_message("Could not save your changes. Please try again.")
        return user
    io_manager.display_message("\nProfile updated.")
    io_manager.display_user(updated)
    return updated


def delete_profile_flow(user: dict) -> dict | None:
    """DELETE the profile, its maintenance history and its saved checks, after a y/n
    confirmation. Returns None if deleted (logs the user out), else the same user."""
    plate = user["license_plate"]
    service_count = len(data_manager.history_for_plate(plate))
    check_count = len(data_manager.query(lambda r: r.get("license_plate") == plate))

    question = (f"Permanently delete {plate}, its {service_count} service(s) and "
                f"{check_count} urgency check(s)?")
    if not io_manager.confirm_action(question):
        io_manager.display_message("Delete cancelled.")
        return user

    # Only remove the car's checks once the profile itself is gone.
    if not data_manager.delete_user(plate):
        io_manager.display_message("Could not delete the profile. Please try again.")
        return user
    data_manager.delete_history_for_plate(plate)
    data_manager.delete_records_for_plate(plate)
    io_manager.display_message("Profile, history and checks deleted. You have been logged out.")
    return None


# ======================================================================
# THE MAIN LOOP: show the menu, do what the user picks, repeat
# ======================================================================

def hide_google_notices(record: logging.LogRecord) -> bool:
    """Log filter: hide Google AI library warnings that clutter the screen.
    Returns False (hide) only for google_genai messages below ERROR level."""
    from_google = record.name.startswith("google_genai")
    is_minor = record.levelno < logging.ERROR
    return not (from_google and is_minor)


def main() -> None:
    """Run the app: set up logging, then show the menu and handle choices until Exit.
    Returns nothing."""
    # Only io_manager may print(), so the other managers report problems via logging.
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(name)s: %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(hide_google_notices)

    # The logged-in profile is passed to each flow; no global variables.
    current_user = None   # None = logged out

    try:
        while True:
            choice = io_manager.prompt_main_menu(current_user)

            if current_user is None:
                # ---------- Logged-out menu ----------
                if choice == "1":
                    current_user = login_flow()
                elif choice == "2":
                    current_user = register_flow()
                elif choice == "3":
                    io_manager.display_message("Goodbye!")
                    break
                else:
                    io_manager.display_message("Invalid choice. Please enter a number from the menu.")
            else:
                # ---------- Logged-in menu ----------
                # Options 1-7 pause so results aren't pushed off screen by the menu.
                if choice == "1":
                    add_service_flow(current_user)
                    io_manager.wait_for_enter()
                elif choice == "2":
                    history_flow(current_user)
                    io_manager.wait_for_enter()
                elif choice == "3":
                    edit_service_flow(current_user)
                    io_manager.wait_for_enter()
                elif choice == "4":
                    delete_service_flow(current_user)
                    io_manager.wait_for_enter()
                elif choice == "5":
                    check_part_flow(current_user)
                    io_manager.wait_for_enter()
                elif choice == "6":
                    urgent_flow(current_user)
                    io_manager.wait_for_enter()
                elif choice == "7":
                    io_manager.display_user(current_user)
                    io_manager.wait_for_enter()
                elif choice == "8":
                    current_user = update_profile_flow(current_user)
                elif choice == "9":
                    current_user = delete_profile_flow(current_user)   # None = logged out
                elif choice == "10":
                    io_manager.display_message(f"Logged out {current_user['name']}.")
                    current_user = None
                elif choice == "11":
                    io_manager.display_message("Goodbye!")
                    break
                else:
                    io_manager.display_message("Invalid choice. Please enter a number from the menu.")

    except (KeyboardInterrupt, EOFError):
        # Ctrl+C, or no keyboard attached (e.g. Docker run without -it): exit politely.
        io_manager.display_message("\nExiting. (If you're using Docker, run with: docker run -it ...)")


# Start the app only when run directly, not when the tests import this file.
if __name__ == "__main__":
    main()
