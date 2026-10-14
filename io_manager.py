"""
io_manager.py -- the Input layer: the screen and keyboard of the app.

Every print() and input() in the whole app lives here (project brief, section 2.1).
It shows menus and results, reads what the user types, and rejects bad input with
a message and a re-prompt. It hands clean values back to main.py and never saves
files, calls the AI or makes business decisions; main.py passes in any saved data
it needs (e.g. plates already taken). Pipeline: io -> ai -> logic -> data.

How to read this file:
- FIXED SETTINGS: menu text, the plate pattern and the date format used everywhere.
- HELPERS: small functions that convert or tidy values (dates, km, plates).
- VALIDATED QUESTIONS: ask, check, and ask again until the answer is valid.
- MAIN MENU / ACCOUNT / MAINTENANCE sections: the questions for each menu option.
- SHOWING RESULTS: print saved records and tables without crashing on bad data.

Python idea used all over this file: a type hint such as `label: str` or `-> int`
only documents what type a value should be; `str | None` means "text, or nothing".
"""
# IMPORTS

# datetime: Python's built-in tools for real calendar dates (today, checking dates).
import datetime
# re: "regular expressions", a mini-language for checking the shape of text (plates).
import re

# FIXED SETTINGS

# CAPITAL names are "constants": settings that never change while the app runs.
# Triple quotes """...""" let one string span many lines, so the menu looks as typed.
MENU_LOGGED_OUT = """
==== Car Maintenance & Service Risk Tracker ====
Not logged in
1) Login
2) Register new profile
3) Exit
"""

# {name}, {plate} and {car_model} are filled in by prompt_main_menu().
# The {...} gaps are placeholders; .format(name=...) later swaps in the real values.
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
# Pattern parts: ^ = start, [A-Z]{1,3} = 1 to 3 capital letters, \d{1,4} = 1 to 4
# digits, [A-Z] = one capital letter, $ = end. re.compile() prepares it once for reuse.
LICENSE_PLATE_PATTERN = re.compile(r"^[A-Z]{1,3}\d{1,4}[A-Z]$")

# Sanity cap: any odometer reading above this is treated as a typing mistake.
# The underscores in 2_000_000 are only for readability; Python ignores them.
MAX_ODOMETER_KM = 2_000_000

# Users type, see and save dates as DD-MM-YYYY. parse_date() validates
# the input and show_date() safely formats saved values for the screen.
# "%d-%m-%Y" is the code for day-month-4-digit-year, e.g. "12-10-2026".
DATE_FORMAT = "%d-%m-%Y"
# DATE_HINT is the human-friendly version shown inside the questions.
DATE_HINT = "DD-MM-YYYY"


# HELPERS: converting and formatting values

def parse_date(typed: str) -> datetime.date | None:
    """Turn a typed DD-MM-YYYY date into a real date object.

    Needs:   typed -- the text the user typed, e.g. "12-10-2026".
    Returns: a date object for 12 October 2026, or None if the text is not a real
             date in that format, e.g. "31-02-2025" (no 31 Feb) or "2025/02/01".
    """
    # try/except: attempt something that might fail, and handle the failure calmly.
    try:
        # strptime ("string parse time") reads the text using DATE_FORMAT;
        # .date() keeps only the day part (no hours/minutes).
        return datetime.datetime.strptime(typed, DATE_FORMAT).date()
    # strptime raises ValueError when the text does not fit; we return None instead,
    # so the caller can show a friendly message rather than the program crashing.
    except ValueError:                                    # wrong format or impossible date
        return None


def show_date(saved_date) -> str:
    """Turn a saved date into tidy 'DD-MM-YYYY' text for the screen.

    Needs:   saved_date -- the date as stored in a record, e.g. "12-10-2026".
    Returns: "12-10-2026"; "-" if the date is missing (None or ""); or the raw value
             unchanged if it is damaged (e.g. "soon"), so the screen never crashes.
    """
    # "not saved_date" is True for None and for "" (empty), i.e. no date saved.
    if not saved_date:
        return "-"
    try:
        # Read the saved text as a date (str() first in case it is not text),
        # then write it back out with strftime ("string format time").
        date = datetime.datetime.strptime(str(saved_date), DATE_FORMAT).date()
        return date.strftime(DATE_FORMAT)
    except ValueError:
        return str(saved_date)          # damaged record: show as-is instead of crashing


def km(value) -> str:
    """Format a distance with thousands commas for the screen.

    Needs:   value -- a number (or number saved as text), e.g. 69500 or "69500".
    Returns: "69,500"; "-" if missing (None or ""); or the raw value as text if it
             isn't a number, so a damaged record is still shown.
    """
    # Missing value: show a dash instead of the word "None".
    if value is None or value == "":
        return "-"
    # bool is excluded because Python treats True/False as the numbers 1/0.
    # isinstance(x, (int, float)) asks "is x a whole number or a decimal number?".
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # f-string: f"..." puts values inside {}; ":,.0f" = add commas, 0 decimals.
        return f"{value:,.0f}"            # commas, rounded to a whole number
    # .strip() removes spaces at both ends; .isdigit() is True only if all are digits.
    if isinstance(value, str) and value.strip().isdigit():
        # int() turns the text into a number; ":," adds the thousands commas.
        return f"{int(value):,}"          # number saved as text, e.g. "52000"
    return str(value)                     # damaged record: show as-is instead of crashing


def normalise_plate(typed: str) -> str:
    """Tidy a typed licence plate so the same plate always looks the same.

    Needs:   typed -- the plate as typed, e.g. "sba 1234-a".
    Returns: it without spaces or dashes, in capitals, e.g. "SBA1234A".
    """
    # .replace(old, new) swaps text; replacing with "" deletes it. .upper() = capitals.
    # The calls are chained: each one works on the result of the one before.
    return typed.replace(" ", "").replace("-", "").upper()


# VALIDATED QUESTIONS ("reject and re-prompt")
# Each loops until the answer is valid; wrong answers get a "->" message.
# Pattern used: `while True:` repeats forever, and `return` (or `break`) is
# the only way out, so the function cannot finish until the input is valid.

def prompt_text(label: str) -> str:
    """Ask for text that must not be empty.

    Needs:   label -- what to ask for, e.g. "Name".
    Returns: the answer without extra spaces at the ends, e.g. "Darren".
    """
    # Keep asking until a non-empty answer is typed.
    while True:
        # input() shows the question and waits for the user to type and press Enter.
        answer = input(f"{label}: ").strip()
        # Empty text counts as False in an if, so this only passes for real text.
        if answer:
            return answer
        print(f"  -> {label} cannot be empty. Please try again.")


def prompt_km(label: str) -> int:
    """Ask for a whole number of km (commas allowed).

    Needs:   label -- the question, e.g. "Odometer at service (km)".
    Returns: the number as an int, e.g. typing "69,500" gives 69500. It is never
             larger than MAX_ODOMETER_KM (2,000,000).
    """
    while True:
        # Remove commas so "69,500" becomes "69500" before checking it.
        typed = input(f"{label}: ").strip().replace(",", "")
        # isdigit() also rejects negatives, decimals, letters and empty input.
        if not typed.isdigit():
            print(f"  -> {label} must be a whole number of km, e.g. 45200. Please try again.")
        # Sanity cap: a huge number is almost certainly a typing mistake.
        elif int(typed) > MAX_ODOMETER_KM:
            print(f"  -> {label} looks too large (max {MAX_ODOMETER_KM:,} km). Please try again.")
        else:
            # Valid: convert the text to an int and leave the loop.
            return int(typed)


def date_problem(date: datetime.date, earliest: datetime.date | None) -> str | None:
    """Check whether a service date is allowed.

    Needs:   date -- the date typed (already a date object);
             earliest -- 1 Jan of the car's model year, or None for no lower limit.
    Returns: a short reason it is wrong (e.g. "cannot be in the future"), or None if
             the date is fine. Example: "12-10-2026" is fine, but "01-01-2099" is in the future.
    """
    # A service cannot have happened after today.
    if date > datetime.date.today():
        return "cannot be in the future"
    # BUSINESS RULE (model year): a car can't be serviced before it was built,
    # e.g. a 2020 model cannot have a service dated 15-06-2019.
    if earliest is not None and date < earliest:
        # Two f-strings side by side inside ( ) are joined into one message.
        return (f"cannot be before {earliest.strftime(DATE_FORMAT)}, "
                f"because your car is a {earliest.year} model")
    # None here means "no problem found".
    return None


def prompt_past_date(label: str, earliest: datetime.date | None = None) -> str:
    """Ask for a real date that is today or earlier, e.g. a service date.

    Needs:   label -- e.g. "Service date"; earliest -- optional first allowed date
             (from the car's model year). "= None" means it can be left out.
    Returns: the date as saved text, e.g. "12-10-2026".
    """
    while True:
        # Read the typed text and try to turn it into a date (None if invalid).
        date = parse_date(input(f"{label} ({DATE_HINT}): ").strip())
        if date is None:
            print(f"  -> {label} must be a real date in {DATE_HINT} format. Please try again.")
            # continue = skip the rest of this loop round and ask again.
            continue
        # The date is real; now check the business rules (not future, not too early).
        problem = date_problem(date, earliest)
        if problem is not None:
            print(f"  -> {label} {problem}. Please try again.")
        else:
            # Return it as DD-MM-YYYY text, the format that gets saved.
            return date.strftime(DATE_FORMAT)


def prompt_number_choice(label: str, options: list[str]) -> str:
    """Show options as a numbered list (starting at 1) and ask for one number.

    Needs:   label -- e.g. "Part number"; options -- e.g. ["Engine Oil", "Tyres"].
    Returns: the chosen option's text, e.g. typing 1 gives "Engine Oil".
    """
    # enumerate(..., start=1) gives each option together with a counter 1, 2, 3...
    for number, option in enumerate(options, start=1):
        # ":>2" right-aligns the number in 2 spaces.
        print(f"  {number:>2}) {option}")          # right-align so 9) and 10) line up
    while True:
        typed = input(f"{label}: ").strip()
        # Accept only a whole number that is inside the list (1 to how many options).
        # len(options) = how many items are in the list.
        if typed.isdigit() and 1 <= int(typed) <= len(options):
            return options[int(typed) - 1]          # menu starts at 1, list index at 0
        print(f"  -> Please enter a number from 1 to {len(options)}.")


def prompt_multi_choice(label: str, options: list[str]) -> list[str]:
    """Show options as a numbered list and ask for one or more numbers.

    Needs:   label -- e.g. "Part numbers"; options -- the list of parts.
             Numbers can be separated by commas or spaces, e.g. "4,6" or "4 6".
    Returns: a list of the chosen options, each only once, in the order typed,
             e.g. ["Engine Oil", "Oil Filter"].
    """
    for number, option in enumerate(options, start=1):
        print(f"  {number:>2}) {option}")
    while True:
        # Turn commas into spaces, then .split() cuts the text at spaces into a list:
        # "4,6" -> "4 6" -> ["4", "6"]. Extra spaces are ignored.
        typed = input(f"{label} (e.g. 4,6): ").replace(",", " ").split()
        # Valid only if something was typed AND every piece is a number in range.
        # all(...) is True only when the check is True for every item t.
        if typed and all(t.isdigit() and 1 <= int(t) <= len(options) for t in typed):
            # Build the answer list one option at a time.
            chosen = []
            for t in typed:
                option = options[int(t) - 1]
                if option not in chosen:        # typing "4,4" only counts once
                    chosen.append(option)
            return chosen
        print(f"  -> Enter one or more numbers from 1 to {len(options)}, separated by commas.")


def confirm_action(question: str) -> bool:
    """Ask a yes/no question, e.g. "Delete this service?".

    Needs:   question -- the question text; " (y/n)" is added automatically.
    Returns: True for y/yes, False for n/no (any capitals, e.g. "YES").
    """
    while True:
        # .lower() makes "Y" and "YES" match too.
        answer = input(f"{question} (y/n): ").strip().lower()
        # "in (...)" checks whether the answer is one of the listed words.
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        # Anything else: explain and ask again.
        print("  -> Please answer y or n.")


def wait_for_enter() -> None:
    """Pause until Enter is pressed, so results aren't pushed off screen by the menu.

    Needs nothing. Returns nothing (-> None); whatever is typed is ignored.
    """
    # "\n" at the start prints a blank line first.
    input("\nPress Enter to go back to the menu...")


# MAIN MENU

def prompt_main_menu(current_user: dict | None) -> str:
    """Show the right main menu and read the user's choice.

    Needs:   current_user -- the logged-in user's profile (a dict), or None if no one
             is logged in, e.g. {"name": "Darren", "license_plate": "SBA1234A", ...}.
    Returns: exactly what was typed (trimmed), e.g. "5"; main.py handles invalid choices.
    """
    # No user means show the short logged-out menu.
    if current_user is None:
        print(MENU_LOGGED_OUT)
    else:
        # Fill the {name}, {plate} and {car_model} gaps with this user's details.
        # current_user["name"] reads the value saved under the key "name".
        print(MENU_LOGGED_IN.format(name=current_user["name"],
                                    plate=current_user["license_plate"],
                                    car_model=current_user["car_model"]))
    return input("Choose an option: ").strip()


# ACCOUNT: login, register, update, show profile

def prompt_login() -> str:
    """Ask for the licence plate to log in with.

    Needs nothing.
    Returns: the plate tidied, e.g. "sba1234a" -> "SBA1234A". main.py then checks
             whether that plate is registered (this file cannot read saved data).
    """
    print("\n--- Login ---")
    while True:
        # Tidy straight away so spaces, dashes and small letters don't matter.
        plate = normalise_plate(input("License plate: "))
        # Only reject empty input here; the shape is checked when registering.
        if plate:
            return plate
        print("  -> License plate cannot be empty. Please try again.")


def prompt_identity(taken_plates: set[str]) -> dict:
    """Ask for a name and a new licence plate when registering.

    Needs:   taken_plates -- a set of plates already registered, e.g. {"SJK8888Z"}.
    Returns: a dict, e.g. {"name": "Darren", "license_plate": "SBA1234A"}.
    """
    print("\n--- Register new profile ---")
    # Reuse the "must not be empty" question for the name.
    name = prompt_text("Name")
    while True:
        plate = normalise_plate(input("License plate (e.g. SBA1234A): "))
        # Two checks: right shape, and not already registered (taken_plates comes
        # from main.py, because this file may not read the data files).
        # .match() returns a match if the plate fits the pattern, or None if not.
        if not LICENSE_PLATE_PATTERN.match(plate):
            print("  -> License plate must look like SBA1234A (letters, digits, then a letter). Please try again.")
        elif plate in taken_plates:
            print(f"  -> {plate} is already registered. Please try again.")
        else:
            # A dict stores values under named keys: {"key": value, ...}.
            return {"name": name, "license_plate": plate}


def prompt_car_choice(car_models: list[str]) -> str:
    """Ask which supported car the user drives.

    Needs:   car_models -- the model names from cars.json (passed in by main.py).
    Returns: the chosen model name as text, e.g. the 1st model if "1" is typed.
    """
    print("\nWhich car do you drive?")
    # Reuse the numbered-list question instead of writing the loop again.
    return prompt_number_choice("Car number", car_models)


def coe_problem(coe: datetime.date, earliest: datetime.date | None,
                latest: datetime.date | None) -> str | None:
    """Check a COE expiry date is inside the allowed range.

    Needs:   coe -- the typed expiry date; earliest and latest -- the limits worked out
             by logic_manager.coe_date_range (either may be None = no limit).
    Returns: a short reason it is wrong, or None if it is fine.
             Example: if latest is 31-12-2030, then 01-01-2031 is rejected.
    """
    # BUSINESS RULE (model year): the COE can't expire before the car's model year.
    if earliest is not None and coe < earliest:
        return (f"cannot be before {earliest.strftime(DATE_FORMAT)}, "
                f"because your car is a {earliest.year} model")
    # BUSINESS RULE (COE within 10 years): a COE lasts at most 10 years,
    # so the expiry can't be later than `latest`.
    if latest is not None and coe > latest:
        return (f"cannot be after {latest.strftime(DATE_FORMAT)}: "
                "a COE lasts at most 10 years")
    return None


def prompt_coe_expiry(earliest: datetime.date | None = None,
                      latest: datetime.date | None = None) -> str:
    """Ask for the COE (Certificate of Entitlement) expiry date.

    Needs:   earliest and latest -- optional limits (see coe_problem).
    Returns: the date as saved text, e.g. "12-10-2030".
    """
    while True:
        # Unlike service dates, a past date IS allowed: an expired COE is real
        # information that the business rules act on.
        coe = parse_date(input(f"COE expiry date ({DATE_HINT}): ").strip())
        # Step 1: is it a real date at all?
        if coe is None:
            print(f"  -> COE expiry date must be a real date in {DATE_HINT} format. Please try again.")
        # Step 2: is it inside the allowed range? (coe_problem gives the reason text.)
        elif coe_problem(coe, earliest, latest) is not None:
            print(f"  -> COE expiry date {coe_problem(coe, earliest, latest)}. Please try again.")
        else:
            return coe.strftime(DATE_FORMAT)


def prompt_updated_profile(current: dict, earliest: datetime.date | None = None,
                           latest: datetime.date | None = None) -> dict:
    """Let the user change their name and COE expiry date.

    Needs:   current -- the saved profile dict; earliest/latest -- COE date limits.
             Pressing Enter on a question keeps the old value.
    Returns: an updated copy of the profile, e.g. with "coe_expiry_date" changed
             to "12-10-2030"; main.py saves it.
    """
    print("\n--- Update profile (press Enter to keep the current value) ---")
    # Plate and car identify the account, so they are shown but not editable.
    print(f"License plate: {current['license_plate']} (cannot be changed)")
    print(f"Car:           {current['car_model']} ({current['car_condition']}) (cannot be changed)")

    # dict(current) makes a separate copy. Changing `updated` won't touch the saved
    # profile, so nothing changes unless main.py decides to save the copy.
    updated = dict(current)   # edit a copy; the original is untouched until main.py saves

    # The old name is shown in [ ]; an empty answer keeps it.
    new_name = input(f"Name [{current['name']}]: ").strip()
    if new_name:
        updated["name"] = new_name

    # Ask for the COE date until it is valid, or the user presses Enter to keep it.
    while True:
        typed = input(f"COE expiry date ({DATE_HINT}) [{show_date(current['coe_expiry_date'])}]: ").strip()
        # break = leave the loop now (without returning from the function yet).
        if not typed:
            break                      # empty input = keep the old date
        coe = parse_date(typed)
        if coe is None:
            print(f"  -> Use {DATE_HINT}, or press Enter to keep.")
        # Same range rules as when registering (model year, max 10 years).
        elif coe_problem(coe, earliest, latest) is not None:
            print(f"  -> COE expiry date {coe_problem(coe, earliest, latest)}.")
        else:
            # Valid new date: store it in the copy, then stop asking.
            updated["coe_expiry_date"] = coe.strftime(DATE_FORMAT)
            break
    return updated


def display_user(user: dict) -> None:
    """Print one user's profile, one detail per line.

    Needs:   user -- the profile dict, e.g. name "Darren", plate "SBA1234A".
    Returns: nothing. A missing field shows as None instead of crashing.
    """
    print("\n--- Profile ---")
    # .get('name') returns None if the key is missing; user['name'] would crash.
    # The extra spaces after each label line the values up in one column.
    print(f"Name:            {user.get('name')}")
    print(f"License plate:   {user.get('license_plate')}")
    print(f"Car model:       {user.get('car_model')}")
    print(f"Car condition:   {user.get('car_condition')}")
    print(f"COE expiry date: {show_date(user.get('coe_expiry_date'))}")


# MAINTENANCE CHECK QUESTIONS

def prompt_part_choice(parts: list[str]) -> str:
    """Ask which part to check for urgency.

    Needs:   parts -- only parts with a stored service interval, e.g. ["Engine Oil", ...].
    Returns: the chosen part name, e.g. "Engine Oil".
    """
    print("\nWhich part are you checking?")
    return prompt_number_choice("Part number", parts)


def prompt_current_odometer(last_service_km: int, last_known_odometer: int | None,
                            max_plausible: int | None = None) -> int:
    """Ask for today's odometer reading for an urgency check.

    Needs:   last_service_km -- odometer at this part's last service, e.g. 60,000;
             last_known_odometer -- newest reading on file for the car (or None);
             max_plausible -- highest believable reading today, from logic_manager.
    Returns: the reading as an int, e.g. 69500.
    """
    # Show the last reading on file (if any) so the user knows the minimum allowed.
    if last_known_odometer is not None:
        print(f"(Last odometer reading on file for this car: {last_known_odometer:,} km)")

    # BUSINESS RULE 1 (input validation): an odometer only goes up, so today's
    # reading may not be below the last-service reading or the last reading on file.
    while True:
        # prompt_km already checks it is a whole number within the sanity cap.
        current_odometer = prompt_km("Current odometer reading (km)")
        # Rule 1, check A: not below the reading at the part's last service.
        if current_odometer < last_service_km:
            print(f"  -> Can't be lower than the odometer at last service ({last_service_km:,} km). Please try again.")
        # Rule 1, check B: not below the newest reading saved for this car.
        elif last_known_odometer is not None and current_odometer < last_known_odometer:
            print(f"  -> Can't be lower than the last reading on file ({last_known_odometer:,} km). Please try again.")
        elif max_plausible is not None and current_odometer > max_plausible:
            # Plausibility rule: no more than 2,000 km a day since the last reading.
            print(f"  -> {current_odometer:,} km is more than the car could have driven since your last "
                  f"reading (at most {max_plausible:,} km). Please check and try again.")
        else:
            # Passed every check: hand the reading back to main.py.
            return current_odometer


# MAINTENANCE HISTORY QUESTIONS (add, choose, edit)

def prompt_service_action(part_name: str, current_action: str | None = None,
                          allow_keep: bool = False) -> str | None:
    """Ask what was done to one part: inspect, replace, or (Tyres only) rotate.

    Needs:   part_name -- e.g. "Engine Oil"; current_action -- the old action when
             editing (may be None); allow_keep -- True when editing, so Enter keeps it.
    Returns: the chosen action, e.g. "replace"; or None when editing and Enter was
             pressed (meaning "keep the old action", or leave it unknown if it had none).
    """
    # Every part can be inspected or replaced.
    actions = ["inspect", "replace"]
    # BUSINESS RULE (rotate only for Tyres): only Tyres get the extra "rotate" option.
    if part_name == "Tyres":
        actions.append("rotate")
    print(f"\nWhat was done to {part_name}?")
    for number, action in enumerate(actions, start=1):
        print(f"  {number:>2}) {action}")
    label = "Action number"
    # When editing, show the old action in [ ]; "or 'unknown'" is used if it is None.
    # += adds text to the end of the existing label.
    if allow_keep:
        label += f" [{current_action or 'unknown'}] (Enter keeps it)"
    while True:
        typed = input(f"{label}: ").strip()
        # Enter pressed while editing = keep the old action ...
        if not typed and allow_keep:
            # ... unless the part was changed away from Tyres and the old action was
            # "rotate": that would break the Tyres-only rule, so a new choice is needed.
            if current_action == "rotate" and part_name != "Tyres":
                print("  -> Rotation is only allowed for Tyres. Choose the action for this part.")
            else:
                return None
        # A valid number from the list: return that action (list index starts at 0).
        elif typed.isdigit() and 1 <= int(typed) <= len(actions):
            return actions[int(typed) - 1]
        # Anything else (including Enter when not editing) is rejected.
        else:
            print(f"  -> Please enter a number from 1 to {len(actions)}.")


def prompt_service_entry(parts: list[str], part_name: str | None = None,
                         earliest: datetime.date | None = None) -> dict:
    """Ask for one workshop invoice, which can cover several parts.

    Needs:   parts -- the parts to choose from; part_name -- if given, that part is
             used and the part question is skipped; earliest -- first allowed date.
    Returns: a dict, e.g. {"part_names": ["Engine Oil"],
             "service_actions": {"Engine Oil": "replace"}, "service_date": "12-10-2026",
             "service_odometer": 69500, "notes": "ABC Motors"}.
             The date, odometer and note are asked once and shared by every part.
    """
    print("\n--- Add an invoice (from your workshop invoice) ---")
    # No part given: let the user pick one or more parts from the invoice.
    if part_name is None:
        print("Which parts were serviced on this invoice?")
        part_names = prompt_multi_choice("Part numbers", parts)
    else:
        # Part already known: put it in a one-item list so the rest works the same way.
        print(f"Part: {part_name}")
        part_names = [part_name]
    # Ask what was done to each chosen part; store it as {part name: action}.
    service_actions = {}
    for name in part_names:
        service_actions[name] = prompt_service_action(name)
    # Shared details: date (not future, not before model year) and odometer.
    service_date = prompt_past_date("Service date", earliest)
    service_odometer = prompt_km("Odometer at service (km)")
    # Notes are optional, so an empty answer is fine here (no loop needed).
    notes = input("Workshop / notes (optional, press Enter to skip): ").strip()
    return {"part_names": part_names, "service_actions": service_actions, "service_date": service_date,
            "service_odometer": service_odometer, "notes": notes}


def prompt_service_choice(entries: list[dict], action: str) -> dict | None:
    """Show the car's services as a numbered list and ask which one to use.

    Needs:   entries -- the saved service entries; action -- the word for the question,
             e.g. "edit" or "delete".
    Returns: the chosen entry dict, or None if 0 is typed (cancel).
    """
    print(f"\nWhich service do you want to {action}? (0 = cancel)")
    # One line per service. .get() is used so a missing field can't crash the list.
    # Layout codes: :<18 = left-align in 18 spaces, :>9 = right-align in 9 spaces.
    # str(...) is needed so the layout codes also work when a value is None.
    for number, entry in enumerate(entries, start=1):
        print(f"  {number:>2}) {show_date(entry.get('service_date'))}  "
              f"{str(entry.get('part_name')):<18} {km(entry.get('service_odometer')):>9} km  "
              f"{str(entry.get('service_action') or 'unknown'):<8}  "
              f"{entry.get('notes') or ''}")
    while True:
        typed = input("Service number: ").strip()
        # 0 lets the user back out without choosing anything.
        if typed == "0":
            return None
        if typed.isdigit() and 1 <= int(typed) <= len(entries):
            return entries[int(typed) - 1]
        print(f"  -> Please enter a number from 1 to {len(entries)}, or 0 to cancel.")


def prompt_updated_service(current: dict, parts: list[str],
                           earliest: datetime.date | None = None) -> dict:
    """Let the user edit one saved service: part, action, date, odometer and note.

    Needs:   current -- the saved service entry; parts -- the part list;
             earliest -- first allowed service date (model year).
             Pressing Enter on a question keeps the old value.
    Returns: an updated copy, e.g. odometer changed from 69,000 to 69,500;
             main.py checks it and saves it.
    """
    print("\n--- Edit service (press Enter to keep the current value) ---")
    # Work on a copy: if the user's changes fail main.py's checks, or are not saved,
    # the original record is still untouched.
    updated = dict(current)             # edit a copy; main.py saves it

    # 1) PART: show all parts on one line, e.g. "Parts: 1) Engine Oil, 2) Tyres".
    # ", ".join(...) glues the pieces together with ", " between them.
    print("Parts: " + ", ".join(f"{n}) {p}" for n, p in enumerate(parts, start=1)))
    while True:
        typed = input(f"Part number [{current.get('part_name')}]: ").strip()
        # Enter = keep the old part.
        if not typed:
            break
        if typed.isdigit() and 1 <= int(typed) <= len(parts):
            updated["part_name"] = parts[int(typed) - 1]
            break
        print(f"  -> Enter a number from 1 to {len(parts)}, or press Enter to keep.")

    # 2) ACTION: uses the (possibly new) part, so "rotate" is offered only for Tyres.
    action = prompt_service_action(updated.get("part_name"), current.get("service_action"),
                                   allow_keep=True)
    # None means "keep the old action", so only overwrite when a new one was chosen.
    if action is not None:
        updated["service_action"] = action

    # 3) DATE: same rules as a new service (real date, not future, not before model year).
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

    # 4) ODOMETER: a whole number (commas removed) no bigger than the sanity cap.
    while True:
        typed = input(f"Odometer at service (km) [{km(current.get('service_odometer'))}]: ").strip().replace(",", "")
        if not typed:
            break
        if typed.isdigit() and int(typed) <= MAX_ODOMETER_KM:
            updated["service_odometer"] = int(typed)
            break
        print("  -> Enter a whole number of km, or press Enter to keep.")

    # 5) NOTES: "-" clears them, other text replaces them, Enter keeps them.
    # `x or ''` shows an empty string instead of None when there are no notes.
    typed = input(f"Workshop / notes [{current.get('notes') or ''}] (type - to clear): ").strip()
    if typed == "-":
        updated["notes"] = ""
    elif typed:
        updated["notes"] = typed
    return updated


# SHOWING RESULTS (display_record, display_list, display_result per the brief)
# All use .get(), km() and show_date(), so a record with missing or damaged
# fields is still shown instead of crashing the screen.

def display_message(message: str) -> None:
    """Print a message on behalf of main.py, which is not allowed to print.

    Needs:   message -- the text, e.g. "Logged in as SBA1234A."
    Returns: nothing.
    """
    print(message)


# How the stage of a 'first at X, then every Y' rule is shown on screen.
# A dict used as a lookup table: key "first" -> text " (first change)".
STAGE_TEXT = {"first": " (first change)", "repeat": " (after the first change)"}


def schedule_text(record: dict) -> str:
    """Describe a part's service interval in words.

    Needs:   record -- a check record with interval_km, interval_months and, if
             saved, action and interval_stage.
    Returns: e.g. "inspect every 16,000 km or 12 months". A limit of 0 or missing is
             left out (the manual gives none), e.g. "replace every 100,000 km (no time
             limit)". Older records without an action just say "every ...".
    """
    # Read both limits at once (tuple unpacking: a, b = x, y).
    interval_km, months = record.get("interval_km"), record.get("interval_months")
    # A missing or 0 limit counts as False, so `not interval_km` means "no km limit".
    if not interval_km and months:
        text = f"every {months} months (no km limit)"
    elif interval_km and not months:
        text = f"every {km(interval_km)} km (no time limit)"
    else:
        text = f"every {km(interval_km)} km or {months} months"
    # Put the action in front if the record has one, e.g. "replace every ...".
    if record.get("action"):
        text = f"{record['action']} {text}"
    # Add the stage text; .get(..., "") gives "" when there is no stage.
    return text + STAGE_TEXT.get(record.get("interval_stage"), "")


def display_record(record: dict) -> None:
    """Print one maintenance (urgency) check in full, one detail per line.

    Needs:   record -- a saved check, e.g. part "Engine Oil", plate "SBA1234A",
             checked at 69,500 km on "12-10-2026".
    Returns: nothing.
    """
    # The AI score may be missing (None), so prepare friendly text first.
    urgency = record.get("urgency_score")
    if urgency is None:
        urgency_text = "n/a"            # the AI could not give a score
    else:
        urgency_text = f"{urgency}/10"

    # .get() returns None for a missing field, so an old or damaged record still prints.
    print("\n--- Maintenance check ---")
    print(f"Part:               {record.get('part_name')}  ({record.get('car_model')}, {record.get('license_plate')})")
    print(f"Checked on:         {show_date(record.get('check_date'))} at {km(record.get('current_odometer'))} km")
    print(f"Last serviced:      {show_date(record.get('last_service_date'))} at {km(record.get('last_service_mileage'))} km")
    print(f"Schedule:           {schedule_text(record)}")
    print(f"Since last service: {km(record.get('km_since_service'))} km / {record.get('days_since_service')} days")
    if record.get("is_overdue"):        # only shown for overdue parts
        print(f"Overdue by:         {km(record.get('km_overdue'))} km / {record.get('days_overdue')} days")
    print(f"AI urgency:         {urgency_text} (confidence: {record.get('confidence')})")
    # .get(key, 'n/a') gives 'n/a' instead of None when the key is missing.
    print(f"Answered by:        {record.get('ai_provider', 'n/a')}")
    print(f"AI summary:         {record.get('overdue_summary')}")
    print(f"Manual reference:   {record.get('manual_reference')}")
    print(f"OUTCOME:            {record.get('outcome')}")
    print(f"Service by:         {show_date(record.get('recommended_service_date'))}")
    print(f"Risk score:         {record.get('risk_score')}/100")
    print(f"Advice:             {record.get('recommended_action')}")

    # Show whether Brake Pad history contributed to the single AI urgency assessment.
    # Only for Brake Pads, and only if history_context really is a dict (not damaged).
    context = record.get("history_context")
    if record.get("part_name") == "Brake Pads" and isinstance(context, dict):
        # A history_pattern means past replacements were used in the AI assessment.
        if record.get("history_pattern"):
            print(f"History used:       yes ({context.get('replacement_count', 0)} confirmed replacements)")
            print(f"History pattern:    {record.get('history_pattern')}")
        else:
            # History not used: show the count and, if saved, the reason why not.
            print(f"History used:       no ({context.get('replacement_count', 0)} confirmed replacements)")
            if context.get("reason"):
                print(f"History limitation: {context.get('reason')}")


def display_list(records: list[dict]) -> None:
    """Print many checks as a table, one row each (history and urgent views).

    Needs:   records -- a list of saved checks (may be empty).
    Returns: nothing. A row shows: check date, part, odometer (e.g. 69,500),
             urgency, service-by date and outcome.
    """
    # An empty list counts as False: say so and stop (return) early.
    if not records:
        print("\nNo records to show.")
        return

    # Fixed-width columns: :<12 = left-align in 12 chars, :>10 = right-align in 10
    # (so the km figures line up on the right). Header and rows use the same widths.
    print(f"\n{'Checked':<12}{'Part':<20}{'Odometer':>10}  {'Urgency':<8}{'Service by':<12}Outcome")
    # One row per record; r is the current record in the loop.
    for r in records:
        urgency = r.get("urgency_score")
        # One-line if/else: "-" when there is no score, otherwise the score as text.
        urgency_text = "-" if urgency is None else str(urgency)
        # [:19] is "slicing": keep only the first 19 characters.
        part = str(r.get("part_name"))[:19]          # cut to 19 so it fits the 20-wide column
        print(f"{show_date(r.get('check_date')):<12}"
              f"{part:<20}"
              f"{km(r.get('current_odometer')):>10}  "
              f"{urgency_text:<8}"
              f"{show_date(r.get('recommended_service_date')):<12}"
              f"{r.get('outcome')}")


def display_result(record: dict) -> None:
    """Print a check that has just been saved: a banner, then the full details.

    Needs:   record -- the new check, e.g. for "Engine Oil" at 69,500 km.
    Returns: nothing.
    """
    print("\n>>> Assessment saved.")
    # Reuse display_record so the details look the same everywhere.
    display_record(record)


def display_repeated(previous: dict) -> None:
    """Show the earlier saved check when the user re-enters identical details.

    Needs:   previous -- the earlier check with the same details (found by main.py).
    Returns: nothing. The AI is not asked again, saving time and an AI call.
    """
    print("\nThis is repeated information.")
    print(f"You checked this part with the same details on {show_date(previous.get('check_date'))}, "
          "so it was not sent to the AI again. Your saved assessment:")
    display_record(previous)


def display_service(entry: dict) -> None:
    """Print one service entry on one line, e.g. after it has been added or edited.

    Needs:   entry -- a service entry, e.g. "Engine Oil" replaced on "12-10-2026".
    Returns: nothing. The line shows date, part, "at 69,500 km", action and notes.
    """
    # Same column widths as prompt_service_choice so the two lists look alike.
    print(f"  {show_date(entry.get('service_date'))}  {str(entry.get('part_name')):<18} at "
          f"{km(entry.get('service_odometer')):>9} km  "
          f"{entry.get('service_action') or 'unknown'}  {entry.get('notes') or ''}")


def display_history(entries: list[dict]) -> None:
    """Print the car's maintenance history as a table, newest first (in the order
    main.py passes it in).

    Needs:   entries -- service entries; each may carry "latest_check" (added by
             main.py): the newest AI urgency check based on that service.
    Returns: nothing. A row shows: service date, part, action, odometer, urgency,
             check date, short outcome (e.g. "URGENT") and notes.
    """
    if not entries:
        print("\nNo services in your history yet.")
        return
    # Header row; each row below uses the same widths so the columns line up.
    print(f"\n{'Serviced':<12}{'Part':<19}{'Action':<10}{'Odometer':>10}  {'Urgency':<8}{'Checked':<12}"
          f"{'Outcome':<34}Notes")
    for entry in entries:
        check = entry.get("latest_check")
        # No urgency check yet for this service: fill the three columns with defaults.
        # (Three names given three values at once.)
        if check is None:
            urgency_text, checked, outcome = "-", "-", "not checked yet"
        else:
            urgency = check.get("urgency_score")
            urgency_text = "-" if urgency is None else str(urgency)
            checked = show_date(check.get("check_date"))
            # .split(" - ") cuts the outcome text at " - "; [0] keeps the first piece,
            # so only the short label is shown in the table.
            outcome = str(check.get("outcome")).split(" - ")[0]   # e.g. "URGENT"
        # Long text is sliced ([:18], [:33]) so it can't push the next column along.
        print(f"{show_date(entry.get('service_date')):<12}"
              f"{str(entry.get('part_name'))[:18]:<19}"
              f"{str(entry.get('service_action') or 'unknown'):<10}"
              f"{km(entry.get('service_odometer')):>10}  "
              f"{urgency_text:<8}{checked:<12}{outcome[:33]:<34}"
              f"{entry.get('notes') or ''}")