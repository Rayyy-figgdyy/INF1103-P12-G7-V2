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

# Users type and see DD/MM/YYYY; dates are SAVED as YYYY-MM-DD (sorts and
# calculates correctly). parse_date() and show_date() convert between the two.
DATE_FORMAT = "%d/%m/%Y"
DATE_HINT = "DD/MM/YYYY"


# ======================================================================
# HELPERS: converting and formatting values
# ======================================================================

def parse_date(typed: str) -> datetime.date | None:
    """Turn a typed DD/MM/YYYY date (dashes allowed) into a date object.
    Returns None if it isn't a real date, e.g. '31/02/2025'."""
    try:
        cleaned = typed.replace("-", "/")                 # accept 12-10-2026 as well
        return datetime.datetime.strptime(cleaned, DATE_FORMAT).date()
    except ValueError:                                    # wrong format or impossible date
        return None


def show_date(saved_date) -> str:
    """Turn a saved 'YYYY-MM-DD' date into 'DD/MM/YYYY' for the screen.
    Returns '-' if missing, or the raw value if it is damaged."""
    if not saved_date:
        return "-"
    try:
        date = datetime.date.fromisoformat(str(saved_date))
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
    Returns it in the saved format, 'YYYY-MM-DD'."""
    while True:
        date = parse_date(input(f"{label} ({DATE_HINT}): ").strip())
        if date is None:
            print(f"  -> {label} must be a real date in {DATE_HINT} format. Please try again.")
        elif date > datetime.date.today():                # future dates are rejected
            print(f"  -> {label} cannot be in the future. Please try again.")
        else:
            return date.isoformat()


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


