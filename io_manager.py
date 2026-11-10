"""
io_manager.py -- the Input layer: the screen and keyboard of the app.

Every print() and input() in the whole app lives in the IOManager class (project
brief, section 2.1). It shows menus and results, reads what the user types, and
rejects bad input with a message and a re-prompt. It hands clean values back to
the controllers and never saves files, calls the AI or makes business decisions;
the controllers pass in any saved data it needs (e.g. plates already taken).

How the class is organised:
- CLASS ATTRIBUTES: menu text, the plate pattern and the date format used everywhere.
- STATIC HELPERS (@staticmethod): pure convert/format/check functions that need no
  object state (dates, km, plates, date rules, schedule text). They can be called
  as IOManager.km(...) without creating an IOManager.
- INSTANCE METHODS: the questions (prompt_*, confirm_action, wait_for_enter) and the
  screens (display_*). Each question loops until the answer is valid.
"""
from __future__ import annotations

import datetime
import re

from models.user_profile import UserProfile


class IOManager:
    """The app's only console screen: asks questions and shows results."""

    # ---------------------------------------------------------------- settings

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

    # Users type, see and save dates as DD-MM-YYYY.
    DATE_FORMAT = "%d-%m-%Y"
    DATE_HINT = "DD-MM-YYYY"

    # How the stage of a 'first at X, then every Y' rule is shown on screen.
    STAGE_TEXT = {"first": " (first change)", "repeat": " (after the first change)"}

    # ---------------------------------------------------------- static helpers

    @staticmethod
    def parse_date(typed: str) -> datetime.date | None:
        """Turn typed DD-MM-YYYY text into a date, e.g. "12-10-2026" -> 12 Oct 2026.
        Returns None if it is not a real date in that format (e.g. "31-02-2025")."""
        try:
            return datetime.datetime.strptime(typed, IOManager.DATE_FORMAT).date()
        except ValueError:                                # wrong format or impossible date
            return None

    @staticmethod
    def show_date(saved_date) -> str:
        """A saved date as tidy DD-MM-YYYY text: "-" if missing, or the raw value
        unchanged if it is damaged (e.g. "soon"), so the screen never crashes."""
        if not saved_date:
            return "-"
        try:
            date = datetime.datetime.strptime(str(saved_date), IOManager.DATE_FORMAT).date()
            return date.strftime(IOManager.DATE_FORMAT)
        except ValueError:
            return str(saved_date)          # damaged record: show as-is instead of crashing

    @staticmethod
    def km(value) -> str:
        """A distance with thousands commas, e.g. 69500 or "69500" -> "69,500".
        "-" if missing; a non-number is shown as-is so a damaged record still prints."""
        if value is None or value == "":
            return "-"
        # bool is excluded because Python treats True/False as the numbers 1/0.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f"{value:,.0f}"            # commas, rounded to a whole number
        if isinstance(value, str) and value.strip().isdigit():
            return f"{int(value):,}"          # number saved as text, e.g. "52000"
        return str(value)                     # damaged record: show as-is

    @staticmethod
    def normalise_plate(typed: str) -> str:
        """A typed plate without spaces or dashes, in capitals: "sba 1234-a" -> "SBA1234A"."""
        return typed.replace(" ", "").replace("-", "").upper()

    @staticmethod
    def date_problem(date: datetime.date, earliest: datetime.date | None) -> str | None:
        """Why a service date is not allowed (e.g. "cannot be in the future"), or None
        if it is fine. `earliest` is 1 Jan of the car's model year (None = no limit)."""
        if date > datetime.date.today():
            return "cannot be in the future"
        # BUSINESS RULE (model year): a car can't be serviced before it was built.
        if earliest is not None and date < earliest:
            return (f"cannot be before {earliest.strftime(IOManager.DATE_FORMAT)}, "
                    f"because your car is a {earliest.year} model")
        return None

    @staticmethod
    def coe_problem(coe: datetime.date, earliest: datetime.date | None,
                    latest: datetime.date | None) -> str | None:
        """Why a COE expiry date is outside the allowed range, or None if it is fine.
        earliest/latest come from HistoryRules.coe_date_range (None = no limit)."""
        # BUSINESS RULE (model year): the COE can't expire before the car's model year.
        if earliest is not None and coe < earliest:
            return (f"cannot be before {earliest.strftime(IOManager.DATE_FORMAT)}, "
                    f"because your car is a {earliest.year} model")
        # BUSINESS RULE (COE within 10 years): a COE lasts at most 10 years.
        if latest is not None and coe > latest:
            return (f"cannot be after {latest.strftime(IOManager.DATE_FORMAT)}: "
                    "a COE lasts at most 10 years")
        return None

    @staticmethod
    def schedule_text(record: dict) -> str:
        """A check record's service interval in words, e.g.
        "inspect every 16,000 km or 12 months". A 0 or missing limit is left out
        (the manual gives none); older records without an action say "every ..."."""
        interval_km, months = record.get("interval_km"), record.get("interval_months")
        if not interval_km and months:
            text = f"every {months} months (no km limit)"
        elif interval_km and not months:
            text = f"every {IOManager.km(interval_km)} km (no time limit)"
        else:
            text = f"every {IOManager.km(interval_km)} km or {months} months"
        if record.get("action"):
            text = f"{record['action']} {text}"
        return text + IOManager.STAGE_TEXT.get(record.get("interval_stage"), "")

    # ------------------------------------------------------ validated questions
    # Each loops until the answer is valid; wrong answers get a "->" message.

    def prompt_text(self, label: str) -> str:
        """Ask for text that must not be empty; returns it trimmed."""
        while True:
            answer = input(f"{label}: ").strip()
            if answer:
                return answer
            print(f"  -> {label} cannot be empty. Please try again.")

    def prompt_km(self, label: str) -> int:
        """Ask for a whole number of km (commas allowed), at most MAX_ODOMETER_KM."""
        while True:
            typed = input(f"{label}: ").strip().replace(",", "")
            # isdigit() also rejects negatives, decimals, letters and empty input.
            if not typed.isdigit():
                print(f"  -> {label} must be a whole number of km, e.g. 45200. Please try again.")
            elif int(typed) > self.MAX_ODOMETER_KM:
                print(f"  -> {label} looks too large (max {self.MAX_ODOMETER_KM:,} km). Please try again.")
            else:
                return int(typed)

    def prompt_past_date(self, label: str, earliest: datetime.date | None = None) -> str:
        """Ask for a real date that is today or earlier (and not before `earliest`);
        returns it as saved DD-MM-YYYY text."""
        while True:
            date = self.parse_date(input(f"{label} ({self.DATE_HINT}): ").strip())
            if date is None:
                print(f"  -> {label} must be a real date in {self.DATE_HINT} format. Please try again.")
                continue
            problem = self.date_problem(date, earliest)
            if problem is not None:
                print(f"  -> {label} {problem}. Please try again.")
            else:
                return date.strftime(self.DATE_FORMAT)

    def prompt_number_choice(self, label: str, options: list[str]) -> str:
        """Show options numbered from 1 and return the text of the one chosen."""
        for number, option in enumerate(options, start=1):
            print(f"  {number:>2}) {option}")          # right-align so 9) and 10) line up
        while True:
            typed = input(f"{label}: ").strip()
            if typed.isdigit() and 1 <= int(typed) <= len(options):
                return options[int(typed) - 1]          # menu starts at 1, list index at 0
            print(f"  -> Please enter a number from 1 to {len(options)}.")

    def prompt_multi_choice(self, label: str, options: list[str]) -> list[str]:
        """Show options numbered from 1 and ask for one or more numbers ("4,6" or
        "4 6"). Returns the chosen options, each once, in the order typed."""
        for number, option in enumerate(options, start=1):
            print(f"  {number:>2}) {option}")
        while True:
            typed = input(f"{label} (e.g. 4,6): ").replace(",", " ").split()
            if typed and all(t.isdigit() and 1 <= int(t) <= len(options) for t in typed):
                chosen = []
                for t in typed:
                    option = options[int(t) - 1]
                    if option not in chosen:        # typing "4,4" only counts once for that part
                        chosen.append(option)
                return chosen
            print(f"  -> Enter one or more numbers from 1 to {len(options)}, separated by commas.")

    def confirm_action(self, question: str) -> bool:
        """Ask a yes/no question (" (y/n)" is added). True for y/yes, False for n/no."""
        while True:
            answer = input(f"{question} (y/n): ").strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            print("  -> Please answer y or n.")

    def wait_for_enter(self) -> None:
        """Pause until Enter is pressed, so results aren't pushed off screen by the menu."""
        input("\nPress Enter to go back to the menu...")

    # ---------------------------------------------------------------- main menu

    def prompt_main_menu(self, current_user: UserProfile | None) -> str:
        """Show the logged-out or logged-in menu and return exactly what was typed
        (trimmed); the App handles invalid choices."""
        if current_user is None:
            print(self.MENU_LOGGED_OUT)
        else:
            print(self.MENU_LOGGED_IN.format(name=current_user.name,
                                             plate=current_user.license_plate,
                                             car_model=current_user.car_model))
        return input("Choose an option: ").strip()

    # ------------------------------------------------------------------ account

    def prompt_login(self) -> str:
        """Ask for the plate to log in with, tidied (e.g. "sba1234a" -> "SBA1234A").
        AccountController checks whether it is registered."""
        print("\n--- Login ---")
        while True:
            plate = self.normalise_plate(input("License plate: "))
            # Only reject empty input here; the shape is checked when registering.
            if plate:
                return plate
            print("  -> License plate cannot be empty. Please try again.")

    def prompt_identity(self, taken_plates: set[str]) -> dict:
        """Ask for a name and a new, correctly shaped, unused plate when registering.
        Returns e.g. {"name": "Darren", "license_plate": "SBA1234A"}."""
        print("\n--- Register new profile ---")
        name = self.prompt_text("Name")
        while True:
            plate = self.normalise_plate(input("License plate (e.g. SBA1234A): "))
            if not self.LICENSE_PLATE_PATTERN.match(plate):
                print("  -> License plate must look like SBA1234A (letters, digits, then a letter). Please try again.")
            elif plate in taken_plates:
                print(f"  -> {plate} is already registered. Please try again.")
            else:
                return {"name": name, "license_plate": plate}

    def prompt_car_choice(self, car_models: list[str]) -> str:
        """Ask which supported car (from cars.json, passed in) the user drives."""
        print("\nWhich car do you drive?")
        return self.prompt_number_choice("Car number", car_models)

    def prompt_coe_expiry(self, earliest: datetime.date | None = None,
                          latest: datetime.date | None = None) -> str:
        """Ask for the COE expiry date within earliest..latest; returns DD-MM-YYYY text."""
        while True:
            # Unlike service dates, a past date IS allowed: an expired COE is real
            # information that the business rules act on.
            coe = self.parse_date(input(f"COE expiry date ({self.DATE_HINT}): ").strip())
            if coe is None:
                print(f"  -> COE expiry date must be a real date in {self.DATE_HINT} format. Please try again.")
            elif self.coe_problem(coe, earliest, latest) is not None:
                print(f"  -> COE expiry date {self.coe_problem(coe, earliest, latest)}. Please try again.")
            else:
                return coe.strftime(self.DATE_FORMAT)

    def prompt_updated_profile(self, current: UserProfile,
                               earliest: datetime.date | None = None,
                               latest: datetime.date | None = None) -> UserProfile:
        """Let the user change their name and COE expiry date (Enter keeps the old
        value). Returns an edited COPY; `current` is untouched until AccountController saves."""
        print("\n--- Update profile (press Enter to keep the current value) ---")
        # Plate and car identify the account, so they are shown but not editable.
        print(f"License plate: {current.license_plate} (cannot be changed)")
        print(f"Car:           {current.car_model} ({current.car_condition}) (cannot be changed)")

        updated = current.copy()

        new_name = input(f"Name [{current.name}]: ").strip()
        if new_name:
            updated.name = new_name

        while True:
            typed = input(f"COE expiry date ({self.DATE_HINT}) "
                          f"[{self.show_date(current.coe_expiry_date)}]: ").strip()
            if not typed:
                break                      # empty input = keep the old date
            coe = self.parse_date(typed)
            if coe is None:
                print(f"  -> Use {self.DATE_HINT}, or press Enter to keep.")
            # Same range rules as when registering (model year, max 10 years).
            elif self.coe_problem(coe, earliest, latest) is not None:
                print(f"  -> COE expiry date {self.coe_problem(coe, earliest, latest)}.")
            else:
                updated.coe_expiry_date = coe.strftime(self.DATE_FORMAT)
                break
        return updated

    def display_user(self, user: UserProfile) -> None:
        """Print one user's profile, one detail per line (a missing field shows None)."""
        print("\n--- Profile ---")
        print(f"Name:            {user.name}")
        print(f"License plate:   {user.license_plate}")
        print(f"Car model:       {user.car_model}")
        print(f"Car condition:   {user.car_condition}")
        print(f"COE expiry date: {self.show_date(user.coe_expiry_date)}")

    # ------------------------------------------------------- maintenance check

    def prompt_part_choice(self, parts: list[str]) -> str:
        """Ask which part (one with a stored service interval) to check."""
        print("\nWhich part are you checking?")
        return self.prompt_number_choice("Part number", parts)

    def prompt_current_odometer(self, last_service_km: int, last_known_odometer: int | None,
                                max_plausible: int | None = None) -> int:
        """Ask for today's odometer reading for an urgency check.
        last_service_km: reading at this part's last service; last_known_odometer:
        newest reading on file (or None); max_plausible: highest believable reading."""
        if last_known_odometer is not None:
            print(f"(Last odometer reading on file for this car: {last_known_odometer:,} km)")

        # BUSINESS RULE 1 (input validation): an odometer only goes up, so today's
        # reading may not be below the last-service reading or the last reading on file.
        while True:
            current_odometer = self.prompt_km("Current odometer reading (km)")
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

    # ----------------------------------------------------- maintenance history

    def prompt_service_action(self, part_name: str, current_action: str | None = None,
                              allow_keep: bool = False) -> str | None:
        """Ask what was done to one part: inspect, replace, or (Tyres only) rotate.
        When editing (allow_keep=True), Enter returns None = keep the old action."""
        actions = ["inspect", "replace"]
        # BUSINESS RULE (rotate only for Tyres).
        if part_name == "Tyres":
            actions.append("rotate")
        print(f"\nWhat was done to {part_name}?")
        for number, action in enumerate(actions, start=1):
            print(f"  {number:>2}) {action}")
        label = "Action number"
        if allow_keep:
            label += f" [{current_action or 'unknown'}] (Enter keeps it)"
        while True:
            typed = input(f"{label}: ").strip()
            if not typed and allow_keep:
                # Keeping "rotate" after changing the part away from Tyres would break
                # the Tyres-only rule, so a new choice is needed.
                if current_action == "rotate" and part_name != "Tyres":
                    print("  -> Rotation is only allowed for Tyres. Choose the action for this part.")
                else:
                    return None
            elif typed.isdigit() and 1 <= int(typed) <= len(actions):
                return actions[int(typed) - 1]
            else:
                print(f"  -> Please enter a number from 1 to {len(actions)}.")

    def prompt_service_entry(self, parts: list[str], part_name: str | None = None,
                             earliest: datetime.date | None = None) -> dict:
        """Ask for one workshop invoice, which can cover several parts. The date,
        odometer and note are asked once and shared by every part. Returns e.g.
        {"part_names": [...], "service_actions": {part: action}, "service_date": ...,
         "service_odometer": ..., "notes": ...}."""
        print("\n--- Add an invoice (from your workshop invoice) ---")
        if part_name is None:
            print("Which parts were serviced on this invoice?")
            part_names = self.prompt_multi_choice("Part numbers", parts)
        else:
            print(f"Part: {part_name}")
            part_names = [part_name]
        service_actions = {}
        for name in part_names:
            service_actions[name] = self.prompt_service_action(name)
        service_date = self.prompt_past_date("Service date", earliest)
        service_odometer = self.prompt_km("Odometer at service (km)")
        notes = input("Workshop / notes (optional, press Enter to skip): ").strip()
        return {"part_names": part_names, "service_actions": service_actions, "service_date": service_date,
                "service_odometer": service_odometer, "notes": notes}

    def prompt_service_choice(self, entries: list[dict], action: str) -> dict | None:
        """List the car's services numbered and return the chosen entry (0 = cancel -> None).
        `action` is the verb in the question, e.g. "edit" or "delete"."""
        print(f"\nWhich service do you want to {action}? (0 = cancel)")
        for number, entry in enumerate(entries, start=1):
            print(f"  {number:>2}) {self.show_date(entry.get('service_date'))}  "
                  f"{str(entry.get('part_name')):<18} {self.km(entry.get('service_odometer')):>9} km  "
                  f"{str(entry.get('service_action') or 'unknown'):<8}  "
                  f"{entry.get('notes') or ''}")
        while True:
            typed = input("Service number: ").strip()
            if typed == "0":
                return None
            if typed.isdigit() and 1 <= int(typed) <= len(entries):
                return entries[int(typed) - 1]
            print(f"  -> Please enter a number from 1 to {len(entries)}, or 0 to cancel.")

    def prompt_updated_service(self, current: dict, parts: list[str],
                               earliest: datetime.date | None = None) -> dict:
        """Let the user edit one saved service (part, action, date, odometer, note);
        Enter keeps each old value. Returns an edited copy; HistoryController checks and saves it."""
        print("\n--- Edit service (press Enter to keep the current value) ---")
        updated = dict(current)             # edit a copy; HistoryController saves it

        # 1) PART
        print("Parts: " + ", ".join(f"{n}) {p}" for n, p in enumerate(parts, start=1)))
        while True:
            typed = input(f"Part number [{current.get('part_name')}]: ").strip()
            if not typed:
                break
            if typed.isdigit() and 1 <= int(typed) <= len(parts):
                updated["part_name"] = parts[int(typed) - 1]
                break
            print(f"  -> Enter a number from 1 to {len(parts)}, or press Enter to keep.")

        # 2) ACTION: uses the (possibly new) part, so "rotate" is offered only for Tyres.
        action = self.prompt_service_action(updated.get("part_name"), current.get("service_action"),
                                            allow_keep=True)
        if action is not None:
            updated["service_action"] = action

        # 3) DATE: same rules as a new service (real date, not future, not before model year).
        while True:
            typed = input(f"Service date ({self.DATE_HINT}) "
                          f"[{self.show_date(current.get('service_date'))}]: ").strip()
            if not typed:
                break
            date = self.parse_date(typed)
            if date is None:
                print(f"  -> Use {self.DATE_HINT}, or press Enter to keep.")
            elif self.date_problem(date, earliest) is not None:
                print(f"  -> The service date {self.date_problem(date, earliest)}.")
            else:
                updated["service_date"] = date.strftime(self.DATE_FORMAT)
                break

        # 4) ODOMETER: a whole number (commas removed) no bigger than the sanity cap.
        while True:
            typed = input(f"Odometer at service (km) "
                          f"[{self.km(current.get('service_odometer'))}]: ").strip().replace(",", "")
            if not typed:
                break
            if typed.isdigit() and int(typed) <= self.MAX_ODOMETER_KM:
                updated["service_odometer"] = int(typed)
                break
            print("  -> Enter a whole number of km, or press Enter to keep.")

        # 5) NOTES: "-" clears them, other text replaces them, Enter keeps them.
        typed = input(f"Workshop / notes [{current.get('notes') or ''}] (type - to clear): ").strip()
        if typed == "-":
            updated["notes"] = ""
        elif typed:
            updated["notes"] = typed
        return updated

    # ---------------------------------------------------------- showing results
    # All use .get(), km() and show_date(), so a record with missing or damaged
    # fields is still shown instead of crashing the screen.

    def display_message(self, message: str) -> None:
        """Print a message on behalf of the controllers, which are not allowed to print."""
        print(message)

    def display_record(self, record: dict) -> None:
        """Print one maintenance (urgency) check in full, one detail per line."""
        urgency = record.get("urgency_score")
        urgency_text = "n/a" if urgency is None else f"{urgency}/10"

        print("\n--- Maintenance check ---")
        print(f"Part:               {record.get('part_name')}  ({record.get('car_model')}, {record.get('license_plate')})")
        print(f"Checked on:         {self.show_date(record.get('check_date'))} at {self.km(record.get('current_odometer'))} km")
        print(f"Last serviced:      {self.show_date(record.get('last_service_date'))} at {self.km(record.get('last_service_mileage'))} km")
        print(f"Schedule:           {self.schedule_text(record)}")
        print(f"Since last service: {self.km(record.get('km_since_service'))} km / {record.get('days_since_service')} days")
        if record.get("is_overdue"):        # only shown for overdue parts
            print(f"Overdue by:         {self.km(record.get('km_overdue'))} km / {record.get('days_overdue')} days")
        print(f"AI urgency:         {urgency_text} (confidence: {record.get('confidence')})")
        print(f"Answered by:        {record.get('ai_provider', 'n/a')}")
        print(f"AI summary:         {record.get('overdue_summary')}")
        print(f"Manual reference:   {record.get('manual_reference')}")
        print(f"OUTCOME:            {record.get('outcome')}")
        print(f"Service by:         {self.show_date(record.get('recommended_service_date'))}")
        print(f"Risk score:         {record.get('risk_score')}/100")
        print(f"Advice:             {record.get('recommended_action')}")

        # Brake Pads only: show whether past replacements fed the AI assessment.
        context = record.get("history_context")
        if record.get("part_name") == "Brake Pads" and isinstance(context, dict):
            if record.get("history_pattern"):
                print(f"History used:       yes ({context.get('replacement_count', 0)} confirmed replacements)")
                print(f"History pattern:    {record.get('history_pattern')}")
            else:
                print(f"History used:       no ({context.get('replacement_count', 0)} confirmed replacements)")
                if context.get("reason"):
                    print(f"History limitation: {context.get('reason')}")

    def display_list(self, records: list[dict]) -> None:
        """Print many checks as a table: check date, part, odometer, urgency,
        service-by date and outcome."""
        if not records:
            print("\nNo records to show.")
            return
        print(f"\n{'Checked':<12}{'Part':<20}{'Odometer':>10}  {'Urgency':<8}{'Service by':<12}Outcome")
        for r in records:
            urgency = r.get("urgency_score")
            urgency_text = "-" if urgency is None else str(urgency)
            part = str(r.get("part_name"))[:19]          # cut to fit the 20-wide column
            print(f"{self.show_date(r.get('check_date')):<12}"
                  f"{part:<20}"
                  f"{self.km(r.get('current_odometer')):>10}  "
                  f"{urgency_text:<8}"
                  f"{self.show_date(r.get('recommended_service_date')):<12}"
                  f"{r.get('outcome')}")

    def display_result(self, record: dict) -> None:
        """Print a check that has just been saved: a banner, then the full details."""
        print("\n>>> Assessment saved.")
        self.display_record(record)

    def display_repeated(self, previous: dict) -> None:
        """Show the earlier saved check when the user re-enters identical details
        (the AI is not asked again)."""
        print("\nThis is repeated information.")
        print(f"You checked this part with the same details on {self.show_date(previous.get('check_date'))}, "
              "so it was not sent to the AI again. Your saved assessment:")
        self.display_record(previous)

    def display_service(self, entry: dict) -> None:
        """Print one service entry on one line (date, part, odometer, action, notes)."""
        # Same column widths as prompt_service_choice so the two lists look alike.
        print(f"  {self.show_date(entry.get('service_date'))}  {str(entry.get('part_name')):<18} at "
              f"{self.km(entry.get('service_odometer')):>9} km  "
              f"{entry.get('service_action') or 'unknown'}  {entry.get('notes') or ''}")

    def display_history(self, entries: list[dict]) -> None:
        """Print the maintenance history as a table, in the order given (newest first).
        Each entry may carry "latest_check" (added by HistoryController): the newest AI urgency
        check based on that service."""
        if not entries:
            print("\nNo services in your history yet.")
            return
        print(f"\n{'Serviced':<12}{'Part':<19}{'Action':<10}{'Odometer':>10}  {'Urgency':<8}{'Checked':<12}"
              f"{'Outcome':<34}Notes")
        for entry in entries:
            check = entry.get("latest_check")
            if check is None:
                urgency_text, checked, outcome = "-", "-", "not checked yet"
            else:
                urgency = check.get("urgency_score")
                urgency_text = "-" if urgency is None else str(urgency)
                checked = self.show_date(check.get("check_date"))
                outcome = str(check.get("outcome")).split(" - ")[0]   # short label, e.g. "URGENT"
            print(f"{self.show_date(entry.get('service_date')):<12}"
                  f"{str(entry.get('part_name'))[:18]:<19}"
                  f"{str(entry.get('service_action') or 'unknown'):<10}"
                  f"{self.km(entry.get('service_odometer')):>10}  "
                  f"{urgency_text:<8}{checked:<12}{outcome[:33]:<34}"
                  f"{entry.get('notes') or ''}")
