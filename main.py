# main.py -- Car Maintenance & Service Risk Tracker. Run with: python main.py
# Coordinate profiles, service history and maintenance assessments.
# Only main.py connects the four managers; input and output stay in io_manager.py.

import datetime
import logging

import ai_manager
import data_manager
import io_manager
import logic_manager


# ======================================================================
# PIPELINE AND SHARED HELPERS
# ======================================================================

# Run one maintenance check through AI, then apply deterministic business rules.
# raw_record has car, part, odometer and manufacturer interval details.
def build_record(raw_record: dict, manual_path: str | None = None) -> dict:
    # AI combines the manual and any eligible Brake Pad history into one urgency score.
    ai_result = ai_manager.process(raw_record, manual_path=manual_path)
    final_record = dict(ai_result)  # Copy so the AI result is not edited in place.

    # Apply the official schedule after receiving the AI response.
    final_record.update(logic_manager.evaluate(final_record))
    # Risk score orders the urgent list; it is not the final decision.
    final_record["risk_score"] = logic_manager.score(final_record)
    # Routing combines AI results with mandatory safety and overdue rules.
    final_record["outcome"] = logic_manager.route(final_record)
    return final_record


# Return the earliest service date, or None when the model year is unknown.
def earliest_service_date(user: dict) -> datetime.date | None:
    model_year = data_manager.get_model_year(user["car_model"])
    # If the car year is unavailable, the caller handles this missing limit.
    if model_year is None:
        return None
    return datetime.date(model_year, 1, 1)  # The exact build date is unknown.


# Return the first mileage problem, or None when the service fits the history.
def service_problem(user: dict, entries: list[dict], service_date: str, odometer: int,
                    ignore_id: int | None = None) -> str | None:
    # First reject a reading that goes backwards compared with earlier entries.
    problem = logic_manager.check_service_odometer(
        entries, service_date, odometer, ignore_id
    )
    if problem is not None:
        return problem

    # Then reject a distance that is implausible for the elapsed time.
    model_year = data_manager.get_model_year(user["car_model"])
    return logic_manager.check_service_pace(
        entries, service_date, odometer, model_year, ignore_id
    )


# Return the allowed COE expiry date range for the car.
def coe_limits(car_model: str) -> tuple:
    model_year = data_manager.get_model_year(car_model)
    # Use today when checking COE validity.
    return logic_manager.coe_date_range(model_year, datetime.date.today())


# Return the highest odometer reading already saved for the car.
def last_odometer_on_file(license_plate: str) -> int | None:
    # Both past AI checks and workshop services contain odometer readings.
    saved_records = data_manager.load() + data_manager.load_history()
    return data_manager.get_last_odometer(saved_records, license_plate)


# ======================================================================
# MAINTENANCE HISTORY: Create, Read, Update, Delete ("CRUD")
# ======================================================================

# Ask for an invoice until its date and mileage fit the saved history.
def prompt_valid_invoice(user: dict, history: list[dict], parts: list[str],
                         part_name: str | None = None) -> dict | None:
    # Repeat the question when an invoice fails validation.
    while True:
        invoice = io_manager.prompt_service_entry(
            parts, part_name, earliest_service_date(user)
        )
        problem = service_problem(
            user, history, invoice["service_date"], invoice["service_odometer"]
        )

        # None means no validation error; the invoice is safe to use.
        if problem is None:
            return invoice

        io_manager.display_message(f"  -> {problem}")
        # Allow the owner to cancel rather than forcing another attempt.
        if not io_manager.confirm_action("Enter this invoice again?"):
            return None


# Save one part from an invoice and return the saved entry.
def save_invoice_part(user: dict, history: list[dict], invoice: dict,
                      part_name: str) -> dict | None:
    # One invoice can cover several parts with different service actions.
    service_action = invoice["service_actions"][part_name]

    # Date, odometer, part and performed action identify an exact duplicate.
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

    # Store a separate JSON history entry for this part.
    entry = {
        "license_plate": user["license_plate"],  # Car that owns this record.
        "part_name": part_name,
        "service_action": service_action,  # Actual action, such as inspect or replace.
        "service_date": invoice["service_date"],
        "service_odometer": invoice["service_odometer"],
        "notes": invoice["notes"],
    }

    # data_manager assigns the service ID and writes the JSON record.
    saved = data_manager.add_service(entry)
    if saved is None:
        io_manager.display_message(
            f"Could not save the {part_name} service. Please try again."
        )
    return saved


# Ask for one invoice and save one history entry for each serviced part.
def save_new_services(user: dict, part_name: str | None = None) -> list[dict]:
    # Only parts defined in the selected car's schedule can be logged.
    parts = data_manager.list_parts(user["car_model"])
    if not parts:
        io_manager.display_message("No service schedule is available for your car.")
        return []

    # The current car's history is used to validate the new invoice.
    history = data_manager.history_for_plate(user["license_plate"])
    invoice = prompt_valid_invoice(user, history, parts, part_name)
    if invoice is None:
        return []

    saved_entries = []
    # Save each selected part individually, retaining one shared invoice.
    for name in invoice["part_names"]:
        saved = save_invoice_part(user, history, invoice, name)
        if saved is not None:  # Ignore duplicates or failed saves.
            saved_entries.append(saved)

    # Display only entries that were actually saved.
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
    # Sort entries newest first so the latest servicing is easy to find.
    entries = logic_manager.sort_history(data_manager.history_for_plate(plate))

    if not entries:
        io_manager.display_message(
            f"\nNo services in the history for {plate} yet. "
            "Choose 1 to add the services you've had done."
        )
        return

    # Limit previous AI assessments to this licence plate.
    saved_checks = data_manager.query(
        lambda record: record.get("license_plate") == plate
    )

    # Build display-only rows with any assessment tied to each service.
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
    # Ignore the entry being edited when comparing it with existing data.
    problem = service_problem(
        user,
        entries,
        updated["service_date"],
        updated["service_odometer"],
        chosen.get("service_id"),
    )
    if problem is not None:
        return problem

    # Also prevent an edit from becoming a duplicate of another service.
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

    # A cancelled selection returns None and leaves history unchanged.
    chosen = io_manager.prompt_service_choice(entries, "edit")
    if chosen is None:
        io_manager.display_message("Edit cancelled.")
        return

    parts = data_manager.list_parts(user["car_model"])
    updated = io_manager.prompt_updated_service(
        chosen, parts, earliest_service_date(user)
    )

    # Validate before saving, otherwise the old entry remains untouched.
    problem = edited_service_problem(user, entries, chosen, updated)
    if problem is not None:
        io_manager.display_message(f"  -> {problem}\nNothing was changed.")
        return

    # Failed JSON saving must not be presented as a successful edit.
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

    # Show the selected record before asking for permanent deletion.
    io_manager.display_service(chosen)
    if not io_manager.confirm_action("Delete this service from your history?"):
        io_manager.display_message("Delete cancelled.")
        return

    # Delete by the unique service ID, not by the visible row number.
    if data_manager.delete_service(chosen.get("service_id")):
        io_manager.display_message("Service deleted.")
    else:
        io_manager.display_message("Could not delete the service. Please try again.")


# ======================================================================
# MAINTENANCE CHECKS
# ======================================================================

# Ask which supported part to check and return its manual and schedule details.
def check_setup(user: dict) -> tuple | None:
    car_model = user["car_model"]
    # The manual is required because AI checks use the manufacturer PDF.
    manual_path = data_manager.get_manual_path(car_model)

    if manual_path is None:
        io_manager.display_message(
            f"The manual for {car_model} is missing, so parts can't be checked."
        )
        return None

    # Supported parts and intervals come from cars.json, not AI guesses.
    parts = data_manager.list_parts(car_model)
    if not parts:
        io_manager.display_message(
            "No service schedule is available, so parts can't be checked."
        )
        return None

    # The chosen part determines the applicable official schedule.
    part_name = io_manager.prompt_part_choice(parts)
    interval = data_manager.get_service_interval(car_model, part_name)
    if interval is None:
        io_manager.display_message(f"No stored service interval for {part_name}.")
        return None

    return manual_path, part_name, interval


# Find the latest service that can reset this part's manufacturer interval.
def latest_service_for_check(user: dict, part_name: str, interval: dict) -> tuple:
    history = data_manager.history_for_plate(user["license_plate"])
    model_year = data_manager.get_model_year(user["car_model"])
    # "inspect" and "replace" must not be treated as the same action.
    required_action = interval.get("action", "replace")

    # Match the latest relevant service using the scheduled action.
    last_service = logic_manager.latest_service(
        history, part_name, required_action, model_year
    )
    return history, model_year, last_service


# Get a usable last service, asking the user to add one when needed.
def resolve_last_service(user: dict, part_name: str, interval: dict) -> tuple | None:
    history, model_year, last_service = latest_service_for_check(
        user, part_name, interval
    )
    from_new = False  # Start by assuming a recorded service is required.

    # Reuse saved information instead of asking the user to type it again.
    if last_service is not None:
        return last_service, history, model_year, from_new

    io_manager.display_message(
        f"\nThere is no {part_name} service in your maintenance history yet."
    )

    # Parts with a first/repeat rule can start from the car being new.
    if "repeat_km" in interval and model_year is not None:
        from_new = not io_manager.confirm_action(
            f"Has the {part_name} ever been replaced?"
        )

    if from_new:
        last_service = logic_manager.from_new_service(part_name, model_year)
        return last_service, history, model_year, from_new

    # No matching history: ask whether the owner wants to add a record.
    if not io_manager.confirm_action(f"Add your last {part_name} service now?"):
        return None

    if not save_new_services(user, part_name):
        return None

    # Re-read saved history after the owner enters a new service.
    history, model_year, last_service = latest_service_for_check(
        user, part_name, interval
    )
    # An inspection alone may not reset a replacement/rotation interval.
    if last_service is None:
        io_manager.display_message(
            "The entry was saved, but an inspection does not reset this service interval. "
            "Record the last replacement or rotation before checking this part."
        )
        return None

    return last_service, history, model_year, from_new


# Show which service the maintenance check is using.
def display_check_service(part_name: str, last_service: dict,
                          from_new: bool) -> None:
    # Make the chosen servicing baseline visible to the user.
    if from_new:
        io_manager.display_message(
            f"\nChecking your {part_name} from new "
            "(the manual's first-change interval applies):"
        )
    else:
        io_manager.display_message(
            f"\nUsing your last {part_name} service from your history:"
        )

    io_manager.display_service(last_service)


# Ask for today's odometer after checking it against saved readings.
def prompt_check_odometer(user: dict, last_service: dict,
                          history: list[dict]) -> int:
    # Saved checks can contain newer mileage than the service log.
    plate = user["license_plate"]
    saved_checks = data_manager.query(
        lambda record: record.get("license_plate") == plate
    )
    latest_reading = logic_manager.latest_reading(history, saved_checks)

    # Use the latest recorded reading to limit implausible new mileage.
    max_plausible = None
    if latest_reading is not None:
        reading_date, reading_odometer = latest_reading
        max_plausible = logic_manager.max_plausible_odometer(
            reading_date, reading_odometer, datetime.date.today()
        )

    # The prompt applies the stored mileage limits before accepting input.
    last_odometer = last_odometer_on_file(plate)
    return io_manager.prompt_current_odometer(
        last_service["service_odometer"], last_odometer, max_plausible
    )


# Build the record sent to AI and add brake history when checking brake pads.
def build_check_record(user: dict, part_name: str, last_service: dict,
                       current_odometer: int, chosen_interval: dict,
                       model_year: int | None) -> dict:
    # Keep a consistent check date across the entire assessment record.
    today = datetime.date.today()
    # Combine profile details with the service selected for this check.
    raw_record = {
        "license_plate": user["license_plate"],
        "car_model": user["car_model"],
        "car_condition": user["car_condition"],
        "coe_expiry_date": user["coe_expiry_date"],
        "part_name": part_name,
        "check_date": today.strftime("%d-%m-%Y"),
        "service_id": last_service.get("service_id"),  # None for a synthetic "from new" entry.
        "last_service_date": last_service["service_date"],
        "last_service_mileage": last_service["service_odometer"],
        # Old records may lack an action.
        "last_service_action": last_service.get("service_action") or "unknown",
        "current_odometer": current_odometer,
    }
    # Add the official first/repeat servicing interval to the record.
    raw_record.update(chosen_interval)

    # Only Brake Pads have the extra personalised history feature.
    if part_name == "Brake Pads":
        brake_history = data_manager.history_for_part(
            user["license_plate"], part_name
        )
        # Logic checks if at least three valid replacements are available.
        context = logic_manager.brake_history_context(
            brake_history, model_year, today, current_odometer
        )
        # Keep the eligibility result and reason, even when not eligible.
        raw_record["history_context"] = {
            "eligible": context["eligible"],
            "replacement_count": context["replacement_count"],  # Count of confirmed replacements.
            "reason": context["reason"],
        }
        # Give AI all relevant raw entries, including inspections and replacements.
        # The validation above must pass before the history can be used.
        if context["eligible"]:
            raw_record["brake_pad_history"] = brake_history

    return raw_record


# Menu option 5: assess one part using the manual, history and current mileage.
def check_part_flow(user: dict) -> None:
    # Stop safely if the manual, part or manufacturer rule is unavailable.
    setup = check_setup(user)
    if setup is None:
        return

    manual_path, part_name, interval = setup
    # Identify a relevant latest service, or request a new one.
    service_details = resolve_last_service(user, part_name, interval)
    if service_details is None:
        return

    last_service, history, model_year, from_new = service_details
    display_check_service(part_name, last_service, from_new)

    # The official interval may change after a part's first replacement.
    part_services = [
        service for service in history
        if service.get("part_name") == part_name
    ]
    # Select the first or repeat rule.
    chosen_interval = logic_manager.choose_interval(interval, part_services)
    # Ask for present mileage only after the servicing baseline is known.
    current_odometer = prompt_check_odometer(user, last_service, history)

    # Collect everything the AI and the rule engine need in one dict.
    raw_record = build_check_record(
        user,
        part_name,
        last_service,
        current_odometer,
        chosen_interval,
        model_year,
    )

    # Reuse a saved answer only if all repeat fields still match.
    previous = data_manager.find_repeat(raw_record)
    if previous is not None:
        io_manager.display_repeated(previous)
        return

    io_manager.display_message(
        "\nAsking the AI to check this part against your manual..."
    )
    # A fresh check passes through AI before deterministic evaluation.
    final_record = build_record(raw_record, manual_path)

    # Show the result even if saving the assessment fails.
    if not data_manager.save(final_record):
        io_manager.display_message(
            "Warning: the assessment could not be saved to disk."
        )
    io_manager.display_result(final_record)


# Menu option 6: show each part's latest assessment needing attention.
def urgent_flow(user: dict) -> None:
    # Show only results saved for the currently logged-in vehicle.
    plate = user["license_plate"]
    saved_checks = data_manager.query(
        lambda record: record.get("license_plate") == plate
    )

    # Older outcomes for the same part should not stay in the urgent list.
    urgent_records = []
    for record in logic_manager.latest_check_per_part(saved_checks):
        if logic_manager.is_urgent(record):  # Keep only outcomes requiring attention.
            urgent_records.append(record)

    # Highest-risk items appear first for quicker attention.
    urgent_records.sort(
        key=lambda record: record.get("risk_score", 0),
        reverse=True,
    )

    if not urgent_records:
        io_manager.display_message(
            "\nNothing needs attention right now: none of your parts' latest "
            "checks are urgent, flagged, overdue or waiting for manual review. "
            "(Choose 2 to see your history.)"
        )
        return

    io_manager.display_list(urgent_records)


# ======================================================================
# ACCOUNTS: login and profile CRUD
# ======================================================================

# Find the profile for a licence plate, or return None if it is not registered.
def login_flow() -> dict | None:
    # The licence plate is the lookup key for a saved user profile.
    plate = io_manager.prompt_login()
    user = data_manager.find_user_by_plate(plate)

    if user is None:
        io_manager.display_message(
            f"No profile for {plate}. Choose 'Register new profile' first."
        )
        return None

    io_manager.display_message(f"\nWelcome back, {user['name']}!")
    return user


# Create and return a new profile, or None if registration cannot be completed.
def register_flow() -> dict | None:
    # Registration needs a populated car catalogue.
    car_models = data_manager.list_car_models()
    if not car_models:
        io_manager.display_message(
            "The car list (data/cars.json) is missing, so you can't register yet."
        )
        return None

    # This set prevents registering two profiles with the same plate.
    taken_plates = {
        user.get("license_plate")
        for user in data_manager.load_users()
    }

    identity = io_manager.prompt_identity(taken_plates)
    car_model = io_manager.prompt_car_choice(car_models)
    car = data_manager.find_car(car_model)
    # The selected car year determines the permitted COE date range.
    earliest_coe, latest_coe = coe_limits(car_model)

    # Save one JSON profile using validated answers from io_manager.
    profile = {
        "name": identity["name"],
        "license_plate": identity["license_plate"],
        "car_model": car_model,
        "car_condition": car["condition"],
        "coe_expiry_date": io_manager.prompt_coe_expiry(
            earliest_coe, latest_coe
        ),
    }

    if not data_manager.save_user(profile):
        io_manager.display_message("Could not save your profile. Please try again.")
        return None

    io_manager.display_message("\nProfile created -- you are now logged in.")
    io_manager.display_user(profile)
    return profile


# Update the name or COE date, keeping the old profile if saving fails.
def update_profile_flow(user: dict) -> dict:
    earliest_coe, latest_coe = coe_limits(user["car_model"])
    updated_profile = io_manager.prompt_updated_profile(
        user, earliest_coe, latest_coe
    )

    # Return the original profile if the updated one cannot be saved.
    if not data_manager.save_user(updated_profile):
        io_manager.display_message("Could not save your changes. Please try again.")
        return user

    io_manager.display_message("\nProfile updated.")
    io_manager.display_user(updated_profile)
    return updated_profile


# Delete a confirmed profile and all records linked to its licence plate.
def delete_profile_flow(user: dict) -> dict | None:
    plate = user["license_plate"]
    # Count linked records so the confirmation explains what will be lost.
    service_count = len(data_manager.history_for_plate(plate))
    check_count = len(
        data_manager.query(lambda record: record.get("license_plate") == plate)
    )

    question = (
        f"Permanently delete {plate}, its {service_count} service(s) and "
        f"{check_count} urgency check(s)?"
    )
    # A declined confirmation leaves the profile and records intact.
    if not io_manager.confirm_action(question):
        io_manager.display_message("Delete cancelled.")
        return user

    if not data_manager.delete_user(plate):
        io_manager.display_message("Could not delete the profile. Please try again.")
        return user

    # Remove history and assessments associated with the deleted plate.
    data_manager.delete_history_for_plate(plate)
    data_manager.delete_records_for_plate(plate)
    io_manager.display_message(
        "Profile, history and checks deleted. You have been logged out."
    )
    return None


# ======================================================================
# MAIN MENU
# ======================================================================

# Hide minor Google library notices while keeping errors visible.
def hide_google_notices(record: logging.LogRecord) -> bool:
    # Avoid cluttering the terminal with non-error SDK messages.
    from_google = record.name.startswith("google_genai")
    is_minor = record.levelno < logging.ERROR
    return not (from_google and is_minor)


# Handle one logged-out menu choice and return the user plus exit request.
def handle_logged_out_choice(choice: str) -> tuple:
    # None means no one has logged in yet.
    current_user = None
    should_exit = False

    if choice == "1":
        current_user = login_flow()
    elif choice == "2":
        current_user = register_flow()
    elif choice == "3":
        io_manager.display_message("Goodbye!")
        should_exit = True
    else:
        io_manager.display_message(
            "Invalid choice. Please enter a number from the menu."
        )

    return current_user, should_exit  # Tell the loop if the app should close.


# Handle one logged-in menu choice and return the user plus exit request.
# Only menu choices changing the profile need a new current_user value.
def handle_logged_in_choice(choice: str, current_user: dict) -> tuple:
    should_exit = False

    if choice == "1":
        add_service_flow(current_user)
    elif choice == "2":
        history_flow(current_user)
    elif choice == "3":
        edit_service_flow(current_user)
    elif choice == "4":
        delete_service_flow(current_user)
    elif choice == "5":
        check_part_flow(current_user)
    elif choice == "6":
        urgent_flow(current_user)
    elif choice == "7":
        io_manager.display_user(current_user)
    elif choice == "8":
        current_user = update_profile_flow(current_user)
    elif choice == "9":
        current_user = delete_profile_flow(current_user)
    elif choice == "10":
        io_manager.display_message(f"Logged out {current_user['name']}.")
        current_user = None
    elif choice == "11":
        io_manager.display_message("Goodbye!")
        should_exit = True
    else:
        io_manager.display_message(
            "Invalid choice. Please enter a number from the menu."
        )

    # Pause after display-heavy options so the user can read results.
    if choice in ("1", "2", "3", "4", "5", "6", "7"):
        io_manager.wait_for_enter()

    return current_user, should_exit  # Return updated login and exit state.


# Run the menus until the user exits.
def main() -> None:
    # Keep warnings and errors visible while filtering minor SDK notices.
    logging.basicConfig(
        level=logging.WARNING,
        format="[%(levelname)s] %(name)s: %(message)s",
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(hide_google_notices)

    # Current login is held in memory until logout or exit.
    current_user = None

    try:
        # Refresh the menu after every action until the user exits.
        while True:
            choice = io_manager.prompt_main_menu(current_user)

            # Different choices are available before and after login.
            if current_user is None:
                current_user, should_exit = handle_logged_out_choice(choice)
            else:
                current_user, should_exit = handle_logged_in_choice(
                    choice, current_user
                )

            if should_exit:  # Stop the main loop after an Exit choice.
                break

    # Ctrl+C and non-interactive Docker exits should end cleanly.
    except (KeyboardInterrupt, EOFError):
        io_manager.display_message(
            "\nExiting. (If you're using Docker, run with: docker run -it ...)"
        )


# Start the app only when run directly, not when tests import this file.
if __name__ == "__main__":
    main()
