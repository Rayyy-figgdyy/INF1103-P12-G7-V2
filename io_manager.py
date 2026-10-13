"""
io_manager.py -- the Input layer: the screen and keyboard of the app.

Every print() and input() in the whole app lives here (project brief, section 2.1).
It shows menus and results, reads what the user types, and rejects bad input with
a message and a re-prompt. It hands clean values back to main.py and never saves
files, calls the AI or makes business decisions; main.py passes in any saved data
it needs (e.g. plates already taken). Pipeline: io -> ai -> logic -> data.

See explanations/io_manager_explained.txt for a full walkthrough.
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
--- Maintenance ---
1) Check a part (AI urgency assessment)
2) View my maintenance history
3) View my urgent / overdue items
--- Account ---
4) View my profile
5) Update my profile
6) Delete my profile
7) Logout
8) Exit
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


def prompt_past_date(label: str) -> str:
    """Ask for a real date that is today or earlier (e.g. last service date).
    Returns it in the saved format, 'DD-MM-YYYY'."""
    while True:
        date = parse_date(input(f"{label} ({DATE_HINT}): ").strip())
        if date is None:
            print(f"  -> {label} must be a real date in {DATE_HINT} format. Please try again.")
        elif date > datetime.date.today():                # future dates are rejected
            print(f"  -> {label} cannot be in the future. Please try again.")
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


def prompt_coe_expiry() -> str:
    """Ask for the COE expiry date. Returns it as 'DD-MM-YYYY'."""
    while True:
        # Unlike service dates, a past date IS allowed: an expired COE is real
        # information that the business rules act on.
        coe = parse_date(input(f"COE expiry date ({DATE_HINT}): ").strip())
        if coe:
            return coe.strftime(DATE_FORMAT)
        print(f"  -> COE expiry date must be a real date in {DATE_HINT} format. Please try again.")


def prompt_updated_profile(current: dict) -> dict:
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
        if coe:
            updated["coe_expiry_date"] = coe.strftime(DATE_FORMAT)
            break
        print(f"  -> Use {DATE_HINT}, or press Enter to keep.")
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

