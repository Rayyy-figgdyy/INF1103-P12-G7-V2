"""
io_manager.py -- the Input layer: the screen and keyboard of the app.

Every print() and input() in the whole app lives here (project brief, section 2.1).
It shows menus and results, reads what the user types, and rejects bad input with
a message and a re-prompt. It hands clean values back to main.py and never saves
files, calls the AI or makes business decisions; main.py passes in any saved data
it needs (e.g. plates already taken). Pipeline: io -> ai -> logic -> data.

"""
import datetime
import re

# ======================================================================
# FIXED SETTINGS
# ======================================================================

MENU_LOGGED_OUT = """
==== Car Maintenance & Service Risk Tracker ====
Not logged in
1) Login
2) Register new profile
3) Exit
"""

# {name}, {plate} and {car_model} are filled in by prompt_main_menu().
MENU_LOGGED_IN = """
==== Car Maintenance & Service Risk Tracker ====
Logged in: {name} | {plate} | {car_model}
--- Maintenance history ---
 1) Add maintenance history
 2) View maintenance history
 3) Edit maintenance history
 4) Delete maintenance history
--- Urgency checks ---
 5) Check a part (AI urgency assessment)
 6) View my urgent / overdue items
--- Account ---
 7) View my profile
 8) Update my profile
 9) Delete my profile
10) Logout
11) Exit
"""

# Singapore plate, e.g. SBA1234A: 1-3 letters, 1-4 digits, 1 letter, nothing else.
LICENSE_PLATE_PATTERN = re.compile(r"^[A-Z]{1,3}\d{1,4}[A-Z]$")

# Sanity cap: any odometer reading above this is treated as a typing mistake.
MAX_ODOMETER_KM = 2_000_000

# Users type, see and save dates as DD-MM-YYYY. parse_date() validates
# the input and show_date() safely formats saved values for the screen.
DATE_FORMAT = "%d-%m-%Y"
DATE_HINT = "DD-MM-YYYY"


# ======================================================================
# HELPERS: converting and formatting values
# ======================================================================

def parse_date(typed: str) -> datetime.date | None:
    """Turn a typed DD-MM-YYYY date into a date object.
    Returns None if it isn't a real date, e.g. '31-02-2025'."""
    try:
        return datetime.datetime.strptime(typed, DATE_FORMAT).date()
    except ValueError:                                    # wrong format or impossible date
        return None


def show_date(saved_date) -> str:
    """Turn a saved 'DD-MM-YYYY' date into 'DD-MM-YYYY' for the screen.
    Returns '-' if missing, or the raw value if it is damaged."""
    if not saved_date:
        return "-"
    try:
        date = datetime.datetime.strptime(str(saved_date), DATE_FORMAT).date()
        return date.strftime(DATE_FORMAT)
    except ValueError:
        return str(saved_date)          # damaged record: show as-is instead of crashing


def km(value) -> str:
    """Format a distance with thousands commas, e.g. 52000 -> '52,000'.
    Returns '-' if missing, or the raw value if it isn't a number."""
    if value is None or value == "":
        return "-"
    # bool is excluded because Python treats True/False as the numbers 1/0.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,.0f}"            # commas, rounded to a whole number
    if isinstance(value, str) and value.strip().isdigit():
        return f"{int(value):,}"          # number saved as text, e.g. "52000"
    return str(value)                     # damaged record: show as-is instead of crashing


def normalise_plate(typed: str) -> str:
    """Tidy a typed plate: remove spaces and dashes, make it upper case.
    Returns e.g. 'SBA1234A' for 'sba 1234-a'."""
    return typed.replace(" ", "").replace("-", "").upper()


# ======================================================================
# VALIDATED QUESTIONS ("reject and re-prompt")
# Each loops until the answer is valid; wrong answers get a "->" message.
# ======================================================================

def prompt_text(label: str) -> str:
    """Ask for non-empty text (e.g. a name). Returns it trimmed."""
    while True:
        answer = input(f"{label}: ").strip()
        if answer:
            return answer
        print(f"  -> {label} cannot be empty. Please try again.")


def prompt_km(label: str) -> int:
    """Ask for a whole number of km (commas allowed, e.g. 45,200).
    Returns it as an int no larger than MAX_ODOMETER_KM."""
    while True:
        typed = input(f"{label}: ").strip().replace(",", "")
        # isdigit() also rejects negatives, decimals, letters and empty input.
        if not typed.isdigit():
            print(f"  -> {label} must be a whole number of km, e.g. 45200. Please try again.")
        elif int(typed) > MAX_ODOMETER_KM:
            print(f"  -> {label} looks too large (max {MAX_ODOMETER_KM:,} km). Please try again.")
        else:
            return int(typed)


def date_problem(date: datetime.date, earliest: datetime.date | None) -> str | None:
    """Check a service date is not in the future and not before `earliest` (the start
    of the car's model year). Returns what's wrong, or None if the date is fine."""
    if date > datetime.date.today():
        return "cannot be in the future"
    if earliest is not None and date < earliest:
        return (f"cannot be before {earliest.strftime(DATE_FORMAT)}, "
                f"because your car is a {earliest.year} model")
    return None


def prompt_past_date(label: str, earliest: datetime.date | None = None) -> str:
    """Ask for a real date that is today or earlier (e.g. a service date), and not
    before `earliest` if given. Returns it in the saved format, 'DD-MM-YYYY'."""
    while True:
        date = parse_date(input(f"{label} ({DATE_HINT}): ").strip())
        if date is None:
            print(f"  -> {label} must be a real date in {DATE_HINT} format. Please try again.")
            continue
        problem = date_problem(date, earliest)
        if problem is not None:
            print(f"  -> {label} {problem}. Please try again.")
        else:
            return date.strftime(DATE_FORMAT)


def prompt_number_choice(label: str, options: list[str]) -> str:
    """Print options as a numbered list starting at 1 and ask for a number.
    Returns the chosen option text."""
    for number, option in enumerate(options, start=1):
        print(f"  {number:>2}) {option}")          # right-align so 9) and 10) line up
    while True:
        typed = input(f"{label}: ").strip()
        if typed.isdigit() and 1 <= int(typed) <= len(options):
            return options[int(typed) - 1]          # menu starts at 1, list index at 0
        print(f"  -> Please enter a number from 1 to {len(options)}.")


def prompt_multi_choice(label: str, options: list[str]) -> list[str]:
    """Print options as a numbered list and ask for one or more numbers, separated by
    commas or spaces (e.g. "4,6" or "4 6"). Returns the chosen options in list order,
    each once."""
    for number, option in enumerate(options, start=1):
        print(f"  {number:>2}) {option}")
    while True:
        typed = input(f"{label} (e.g. 4,6): ").replace(",", " ").split()
        if typed and all(t.isdigit() and 1 <= int(t) <= len(options) for t in typed):
            chosen = []
            for t in typed:
                option = options[int(t) - 1]
                if option not in chosen:        # typing "4,4" only counts once
                    chosen.append(option)
            return chosen
        print(f"  -> Enter one or more numbers from 1 to {len(options)}, separated by commas.")


def confirm_action(question: str) -> bool:
    """Ask a y/n question (y/yes/n/no, any case). Returns True for yes."""
    while True:
        answer = input(f"{question} (y/n): ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  -> Please answer y or n.")


def wait_for_enter() -> None:
    """Pause until Enter is pressed, so results aren't pushed off screen by the menu."""
    input("\nPress Enter to go back to the menu...")


# ======================================================================
# MAIN MENU
# ======================================================================

def prompt_main_menu(current_user: dict | None) -> str:
    """Show the logged-in or logged-out menu and read a choice.
    Returns the raw choice; main.py handles invalid ones."""
    if current_user is None:
        print(MENU_LOGGED_OUT)
    else:
        print(MENU_LOGGED_IN.format(name=current_user["name"],
                                    plate=current_user["license_plate"],
                                    car_model=current_user["car_model"]))
    return input("Choose an option: ").strip()


# ======================================================================
# ACCOUNT: login, register, update, show profile
# ======================================================================

def prompt_login() -> str:
    """Ask for the plate to log in with. Returns it normalised (e.g. 'SBA1234A');
    main.py checks whether it is registered."""
    print("\n--- Login ---")
    while True:
        plate = normalise_plate(input("License plate: "))
        if plate:
            return plate
        print("  -> License plate cannot be empty. Please try again.")


def prompt_identity(taken_plates: set[str]) -> dict:
    """Ask for a name and a new, valid, unused plate when registering.
    Returns {"name": ..., "license_plate": ...}."""
    print("\n--- Register new profile ---")
    name = prompt_text("Name")
    while True:
        plate = normalise_plate(input("License plate (e.g. SBA1234A): "))
        # Two checks: right shape, and not already registered (taken_plates comes
        # from main.py, because this file may not read the data files).
        if not LICENSE_PLATE_PATTERN.match(plate):
            print("  -> License plate must look like SBA1234A (letters, digits, then a letter). Please try again.")
        elif plate in taken_plates:
            print(f"  -> {plate} is already registered. Please try again.")
        else:
            return {"name": name, "license_plate": plate}


def prompt_car_choice(car_models: list[str]) -> str:
    """Ask which supported car (from cars.json) the user drives. Returns the model name."""
    print("\nWhich car do you drive?")
    return prompt_number_choice("Car number", car_models)


def coe_problem(coe: datetime.date, earliest: datetime.date | None,
                latest: datetime.date | None) -> str | None:
    """Check a COE expiry date is inside the allowed range (worked out by
    logic_manager.coe_date_range). Returns what's wrong, or None if it's fine."""
    if earliest is not None and coe < earliest:
        return (f"cannot be before {earliest.strftime(DATE_FORMAT)}, "
                f"because your car is a {earliest.year} model")
    if latest is not None and coe > latest:
        return (f"cannot be after {latest.strftime(DATE_FORMAT)}: "
                "a COE lasts at most 10 years")
    return None


def prompt_coe_expiry(earliest: datetime.date | None = None,
                      latest: datetime.date | None = None) -> str:
    """Ask for the COE expiry date, between earliest and latest if given.
    Returns it as 'DD-MM-YYYY'."""
    while True:
        # Unlike service dates, a past date IS allowed: an expired COE is real
        # information that the business rules act on.
        coe = parse_date(input(f"COE expiry date ({DATE_HINT}): ").strip())
        if coe is None:
            print(f"  -> COE expiry date must be a real date in {DATE_HINT} format. Please try again.")
        elif coe_problem(coe, earliest, latest) is not None:
            print(f"  -> COE expiry date {coe_problem(coe, earliest, latest)}. Please try again.")
        else:
            return coe.strftime(DATE_FORMAT)


def prompt_updated_profile(current: dict, earliest: datetime.date | None = None,
                           latest: datetime.date | None = None) -> dict:
    """Let the user change their name and COE date (Enter keeps the old value).
    Returns an updated copy of the profile; main.py saves it."""
    print("\n--- Update profile (press Enter to keep the current value) ---")
    # Plate and car identify the account, so they are shown but not editable.
    print(f"License plate: {current['license_plate']} (cannot be changed)")
    print(f"Car:           {current['car_model']} ({current['car_condition']}) (cannot be changed)")

    updated = dict(current)   # edit a copy; the original is untouched until main.py saves

    new_name = input(f"Name [{current['name']}]: ").strip()
    if new_name:
        updated["name"] = new_name

    while True:
        typed = input(f"COE expiry date ({DATE_HINT}) [{show_date(current['coe_expiry_date'])}]: ").strip()
        if not typed:
            break                      # empty input = keep the old date
        coe = parse_date(typed)
        if coe is None:
            print(f"  -> Use {DATE_HINT}, or press Enter to keep.")
        elif coe_problem(coe, earliest, latest) is not None:
            print(f"  -> COE expiry date {coe_problem(coe, earliest, latest)}.")
        else:
            updated["coe_expiry_date"] = coe.strftime(DATE_FORMAT)
            break
    return updated


def display_user(user: dict) -> None:
    """Print one user's profile (missing fields show as None, not a crash)."""
    print("\n--- Profile ---")
    print(f"Name:            {user.get('name')}")
    print(f"License plate:   {user.get('license_plate')}")
    print(f"Car model:       {user.get('car_model')}")
    print(f"Car condition:   {user.get('car_condition')}")
    print(f"COE expiry date: {show_date(user.get('coe_expiry_date'))}")


# ======================================================================
# MAINTENANCE CHECK QUESTIONS
# ======================================================================

def prompt_part_choice(parts: list[str]) -> str:
    """Ask which part to check (only parts with a stored interval are listed).
    Returns the part name."""
    print("\nWhich part are you checking?")
    return prompt_number_choice("Part number", parts)


def prompt_current_odometer(last_service_km: int, last_known_odometer: int | None,
                            max_plausible: int | None = None) -> int:
    """Ask for today's odometer reading for an urgency check. max_plausible is the
    highest believable reading (from logic_manager). Returns it as an int."""
    if last_known_odometer is not None:
        print(f"(Last odometer reading on file for this car: {last_known_odometer:,} km)")

    # BUSINESS RULE 1 (input validation): an odometer only goes up, so today's
    # reading may not be below the last-service reading or the last reading on file.
    while True:
        current_odometer = prompt_km("Current odometer reading (km)")
        if current_odometer < last_service_km:
            print(f"  -> Can't be lower than the odometer at last service ({last_service_km:,} km). Please try again.")
        elif last_known_odometer is not None and current_odometer < last_known_odometer:
            print(f"  -> Can't be lower than the last reading on file ({last_known_odometer:,} km). Please try again.")
        elif max_plausible is not None and current_odometer > max_plausible:
            # Plausibility rule: no more than 2,000 km a day since the last reading.
            print(f"  -> {current_odometer:,} km is more than the car could have driven since your last "
                  f"reading (at most {max_plausible:,} km). Please check and try again.")
        else:
            return current_odometer


# ======================================================================
# MAINTENANCE HISTORY QUESTIONS (add, choose, edit)
# ======================================================================

def prompt_service_entry(parts: list[str], part_name: str | None = None,
                         earliest: datetime.date | None = None) -> dict:
    """Ask for one workshop invoice: the part(s) serviced, then the date, odometer and
    an optional note, typed once for the whole invoice. part_name skips the part
    question when it is already known; earliest is the first allowed service date.
    Returns {"part_names": [...], "service_date", "service_odometer", "notes"}."""
    print("\n--- Add an invoice (from your workshop invoice) ---")
    if part_name is None:
        print("Which parts were serviced on this invoice?")
        part_names = prompt_multi_choice("Part numbers", parts)
    else:
        print(f"Part: {part_name}")
        part_names = [part_name]
    service_date = prompt_past_date("Service date", earliest)
    service_odometer = prompt_km("Odometer at service (km)")
    notes = input("Workshop / notes (optional, press Enter to skip): ").strip()
    return {"part_names": part_names, "service_date": service_date,
            "service_odometer": service_odometer, "notes": notes}


def prompt_service_choice(entries: list[dict], action: str) -> dict | None:
    """Show the car's services as a numbered list and ask which one to edit or delete.
    Entering 0 cancels. Returns the chosen entry, or None if cancelled."""
    print(f"\nWhich service do you want to {action}? (0 = cancel)")
    for number, entry in enumerate(entries, start=1):
        print(f"  {number:>2}) {show_date(entry.get('service_date'))}  "
              f"{str(entry.get('part_name')):<18} {km(entry.get('service_odometer')):>9} km  "
              f"{entry.get('notes') or ''}")
    while True:
        typed = input("Service number: ").strip()
        if typed == "0":
            return None
        if typed.isdigit() and 1 <= int(typed) <= len(entries):
            return entries[int(typed) - 1]
        print(f"  -> Please enter a number from 1 to {len(entries)}, or 0 to cancel.")


def prompt_updated_service(current: dict, parts: list[str],
                           earliest: datetime.date | None = None) -> dict:
    """Let the user change a service's part, date, odometer and note (Enter keeps the
    old value); a new date can't be before `earliest`.
    Returns an updated copy; main.py checks it and saves it."""
    print("\n--- Edit service (press Enter to keep the current value) ---")
    updated = dict(current)             # edit a copy; main.py saves it

    print("Parts: " + ", ".join(f"{n}) {p}" for n, p in enumerate(parts, start=1)))
    while True:
        typed = input(f"Part number [{current.get('part_name')}]: ").strip()
        if not typed:
            break
        if typed.isdigit() and 1 <= int(typed) <= len(parts):
            updated["part_name"] = parts[int(typed) - 1]
            break
        print(f"  -> Enter a number from 1 to {len(parts)}, or press Enter to keep.")

    while True:
        typed = input(f"Service date ({DATE_HINT}) [{show_date(current.get('service_date'))}]: ").strip()
        if not typed:
            break
        date = parse_date(typed)
        if date is None:
            print(f"  -> Use {DATE_HINT}, or press Enter to keep.")
        elif date_problem(date, earliest) is not None:
            print(f"  -> The service date {date_problem(date, earliest)}.")
        else:
            updated["service_date"] = date.strftime(DATE_FORMAT)
            break

    while True:
        typed = input(f"Odometer at service (km) [{km(current.get('service_odometer'))}]: ").strip().replace(",", "")
        if not typed:
            break
        if typed.isdigit() and int(typed) <= MAX_ODOMETER_KM:
            updated["service_odometer"] = int(typed)
            break
        print("  -> Enter a whole number of km, or press Enter to keep.")

    typed = input(f"Workshop / notes [{current.get('notes') or ''}] (type - to clear): ").strip()
    if typed == "-":
        updated["notes"] = ""
    elif typed:
        updated["notes"] = typed
    return updated


# ======================================================================
# SHOWING RESULTS (display_record, display_list, display_result per the brief)
# All use .get(), km() and show_date(), so a record with missing or damaged
# fields is still shown instead of crashing the screen.
# ======================================================================

def display_message(message: str) -> None:
    """Print a message on behalf of main.py, which is not allowed to print."""
    print(message)


# How the stage of a 'first at X, then every Y' rule is shown on screen.
STAGE_TEXT = {"first": " (first change)", "repeat": " (after the first change)"}


def schedule_text(record: dict) -> str:
    """Describe the stored interval, e.g. 'inspect every 16,000 km or 12 months',
    leaving out a limit of 0 (the manual gives none), e.g. 'replace every 100,000 km
    (no time limit)'. Older records without an action just say 'every ...'."""
    interval_km, months = record.get("interval_km"), record.get("interval_months")
    if not interval_km and months:
        text = f"every {months} months (no km limit)"
    elif interval_km and not months:
        text = f"every {km(interval_km)} km (no time limit)"
    else:
        text = f"every {km(interval_km)} km or {months} months"
    if record.get("action"):
        text = f"{record['action']} {text}"
    return text + STAGE_TEXT.get(record.get("interval_stage"), "")


def display_record(record: dict) -> None:
    """Print one maintenance check in full, one detail per line."""
    urgency = record.get("urgency_score")
    if urgency is None:
        urgency_text = "n/a"            # the AI could not give a score
    else:
        urgency_text = f"{urgency}/10"

    print("\n--- Maintenance check ---")
    print(f"Part:               {record.get('part_name')}  ({record.get('car_model')}, {record.get('license_plate')})")
    print(f"Checked on:         {show_date(record.get('check_date'))} at {km(record.get('current_odometer'))} km")
    print(f"Last serviced:      {show_date(record.get('last_service_date'))} at {km(record.get('last_service_mileage'))} km")
    print(f"Schedule:           {schedule_text(record)}")
    print(f"Since last service: {km(record.get('km_since_service'))} km / {record.get('days_since_service')} days")
    if record.get("is_overdue"):        # only shown for overdue parts
        print(f"Overdue by:         {km(record.get('km_overdue'))} km / {record.get('days_overdue')} days")
    print(f"AI urgency:         {urgency_text} (confidence: {record.get('confidence')})")
    print(f"Answered by:        {record.get('ai_provider', 'n/a')}")
    print(f"AI summary:         {record.get('overdue_summary')}")
    print(f"Manual reference:   {record.get('manual_reference')}")
    print(f"OUTCOME:            {record.get('outcome')}")
    print(f"Service by:         {show_date(record.get('recommended_service_date'))}")
    print(f"Risk score:         {record.get('risk_score')}/100")
    print(f"Advice:             {record.get('recommended_action')}")


def display_list(records: list[dict]) -> None:
    """Print many checks as a table, one row each (history and urgent views)."""
    if not records:
        print("\nNo records to show.")
        return

    # Fixed-width columns: :<12 = left-align in 12 chars, :>10 = right-align in 10
    # (so the km figures line up on the right). Header and rows use the same widths.
    print(f"\n{'Checked':<12}{'Part':<20}{'Odometer':>10}  {'Urgency':<8}{'Service by':<12}Outcome")
    for r in records:
        urgency = r.get("urgency_score")
        urgency_text = "-" if urgency is None else str(urgency)
        part = str(r.get("part_name"))[:19]          # cut to 19 so it fits the 20-wide column
        print(f"{show_date(r.get('check_date')):<12}"
              f"{part:<20}"
              f"{km(r.get('current_odometer')):>10}  "
              f"{urgency_text:<8}"
              f"{show_date(r.get('recommended_service_date')):<12}"
              f"{r.get('outcome')}")


def display_result(record: dict) -> None:
    """Print a check that has just been saved (banner + full details)."""
    print("\n>>> Assessment saved.")
    display_record(record)


def display_repeated(previous: dict) -> None:
    """Print the earlier saved check when the user re-enters identical details,
    instead of asking the AI again."""
    print("\nThis is repeated information.")
    print(f"You checked this part with the same details on {show_date(previous.get('check_date'))}, "
          "so it was not sent to the AI again. Your saved assessment:")
    display_record(previous)


def display_service(entry: dict) -> None:
    """Print one service entry, e.g. after it has been added or edited."""
    print(f"  {show_date(entry.get('service_date'))}  {str(entry.get('part_name')):<18} at "
          f"{km(entry.get('service_odometer')):>9} km  {entry.get('notes') or ''}")


def display_history(entries: list[dict]) -> None:
    """Print the car's maintenance history as a table, newest first. Each entry may carry
    "latest_check" (added by main.py): the newest AI urgency check based on that service."""
    if not entries:
        print("\nNo services in your history yet.")
        return
    print(f"\n{'Serviced':<12}{'Part':<19}{'Odometer':>10}  {'Urgency':<8}{'Checked':<12}"
          f"{'Outcome':<34}Notes")
    for entry in entries:
        check = entry.get("latest_check")
        if check is None:
            urgency_text, checked, outcome = "-", "-", "not checked yet"
        else:
            urgency = check.get("urgency_score")
            urgency_text = "-" if urgency is None else str(urgency)
            checked = show_date(check.get("check_date"))
            outcome = str(check.get("outcome")).split(" - ")[0]   # e.g. "URGENT"
        print(f"{show_date(entry.get('service_date')):<12}"
              f"{str(entry.get('part_name'))[:18]:<19}"
              f"{km(entry.get('service_odometer')):>10}  "
              f"{urgency_text:<8}{checked:<12}{outcome[:33]:<34}"
              f"{entry.get('notes') or ''}")
