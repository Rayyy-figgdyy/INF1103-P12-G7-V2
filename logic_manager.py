"""
logic_manager.py -- the business rules (Logic layer).

Takes one maintenance check that the AI has already scored and applies our rules:
  - evaluate(): the facts (overdue by km OR time, km/day, COE days left, service-by date)
  - score():    a 0-100 risk score, used only to sort the urgent list
  - route():    the final outcome text; includes the urgency + confidence rule
Rules held here: overdue = whichever limit comes first, brake pads and tyres are
safety-critical, the "service by" date (business rule 3) and the Singapore COE rules.
It also holds the rules for the maintenance history: which service is the latest for
a part, odometer readings that must go up over time (business rule 1), and which AI
check is the latest one for each part.
All arithmetic is done here, not by the AI. No screen, AI or file access.
"""
import datetime    # Python's built-in tools for dates

# ======================================================================
# FIXED SETTINGS
# ======================================================================

# A failure of these parts is a safety risk (stopping and grip), so they get extra
# urgency below. Lower case so they match part names after .lower().
SAFETY_CRITICAL_PARTS = ("brake pads", "tyres")

DAYS_PER_MONTH = 30.44           # average days in a month (so 24 months = 731 days)
COE_DEFER_WINDOW_DAYS = 180      # "COE ends soon" = within 180 days (about 6 months)

# Plausibility limit for odometer readings: even a hard-driven car can't cover more
# than this many km a day on average, so a bigger jump is treated as a typing mistake.
MAX_KM_PER_DAY = 2_000

# A Singapore COE lasts 10 years, so a COE can't expire more than 10 years from today.
COE_MAX_YEARS = 10

# What each stored action is called in the outcome text of rule 5 below.
OVERDUE_WORDING = {"replace": "part", "inspect": "inspection", "rotate": "tyre rotation"}

# Outcomes that need the owner's attention: any outcome starting with one of these
# is listed in menu option 3.
URGENT_PREFIXES = ("URGENT", "FLAGGED", "DUE SOON", "COE EXPIRED", "NEEDS MANUAL REVIEW")


# ======================================================================
# SMALL HELPERS
# ======================================================================

def to_date(value) -> datetime.date | None:
    """Turn saved text like '03-09-2025' into a date.
    Returns None if the value is missing or isn't a valid date."""
    try:
        return datetime.datetime.strptime(str(value), "%d-%m-%Y").date()
    except (TypeError, ValueError):
        return None


def add_days(start: datetime.date, days: int) -> datetime.date:
    """Return the date `days` days after `start`."""
    return start + datetime.timedelta(days=days)


def recommend_service_date(check_date: datetime.date, is_overdue: bool,
                            km_left: int | None, days_left: int | None,
                            km_per_day: float, urgency: int | None,
                            safety_critical: bool) -> datetime.date:
    """BUSINESS RULE 3: work out the "service by" date for one part.
    Starts from the schedule's due date, then brings it forward if the AI's
    urgency is high. Returns the recommended date."""
    # ---- Part A: the schedule's due date ----
    if is_overdue:
        due = check_date
    else:
        # Due when EITHER limit runs out: the time limit, or the km limit reached at
        # the owner's own driving pace. int() rounds down, so we never recommend late.
        possible_dates = []
        if days_left is not None:
            possible_dates.append(add_days(check_date, days_left))
        if km_left is not None and km_per_day > 0:
            days_until_km_limit = int(km_left / km_per_day)
            possible_dates.append(add_days(check_date, days_until_km_limit))
        if possible_dates:
            due = min(possible_dates)       # min = the earliest date
        else:
            due = check_date

    # ---- Part B: the AI's urgency can bring it forward ----
    # Urgency 8-10: within 3 days. Urgency 5-7: within 14 days. 1-4: keep Part A.
    if urgency is not None and urgency >= 8:
        days_allowed = 3
    elif urgency is not None and urgency >= 5:
        days_allowed = 14
    else:
        days_allowed = None                 # low urgency: keep the schedule's date

    if days_allowed is not None:
        if safety_critical:
            # Brake pads and tyres get half the time (3 -> 1 day, 14 -> 7 days),
            # never less than 1 day.
            days_allowed = max(1, days_allowed // 2)
        # min(): urgency can only bring the date forward, never push it later.
        due = min(due, add_days(check_date, days_allowed))

    return due


# ======================================================================
# evaluate -- work out the facts about one check
# ======================================================================

def evaluate(record: dict) -> dict:
    """Work out the facts about one check: km/days since service, overdue status,
    km per day, safety-critical, COE days left and the "service by" date.
    Returns a NEW dictionary of these facts; the record itself isn't changed."""

    # ---- The dates ----
    # Missing check date -> today; missing last-service date -> 0 days since service.
    check_date = to_date(record.get("check_date")) or datetime.date.today()
    last_service_date = to_date(record.get("last_service_date")) or check_date

    # ---- The stored schedule (business rule 2) ----
    # Intervals always come from our stored schedule (cars.json), never from the AI.
    interval_km = int(record.get("interval_km") or 0)
    interval_days = round((record.get("interval_months") or 0) * DAYS_PER_MONTH)

    # ---- How far, and how long, since the last service ----
    # max(0, ...) guards against bad data giving negative distances or days.
    odometer_now = int(record.get("current_odometer") or 0)
    odometer_at_service = int(record.get("last_service_mileage") or 0)
    km_since = max(0, odometer_now - odometer_at_service)
    days_since = max(0, (check_date - last_service_date).days)

    # ---- Is it overdue? (by distance, by time, or both) ----
    # Overdue when EITHER limit is reached ("10,000 km or 12 months, whichever comes
    # first", as manuals put it). A limit of 0 means the part has no such limit.
    overdue_by_km = interval_km > 0 and km_since >= interval_km
    overdue_by_time = interval_days > 0 and days_since >= interval_days
    is_overdue = overdue_by_km or overdue_by_time

    # ---- How much over, or how much is left ----
    if interval_km > 0:
        km_overdue = max(0, km_since - interval_km)
        km_left = max(0, interval_km - km_since)
    else:
        km_overdue = 0
        km_left = None                      # no km limit for this part
    if interval_days > 0:
        days_overdue = max(0, days_since - interval_days)
        days_left = max(0, interval_days - days_since)
    else:
        days_overdue = 0
        days_left = None                    # no time limit for this part

    # ---- How much the owner drives (km per day) ----
    if days_since > 0:
        km_per_day = km_since / days_since
    else:
        km_per_day = 0.0                    # serviced today: no pace to measure yet

    # ---- Is it a safety-critical part (brake pads or tyres)? ----
    part = str(record.get("part_name", "")).strip().lower()
    safety_critical = part in SAFETY_CRITICAL_PARTS

    # ---- Days until the COE expires (a negative number = already expired) ----
    coe_date = to_date(record.get("coe_expiry_date"))
    if coe_date is not None:
        coe_days_left = (coe_date - check_date).days
    else:
        coe_days_left = None

    # ---- Business rule 3: the "service by" date ----
    service_by = recommend_service_date(check_date, is_overdue, km_left, days_left,
                                         km_per_day, record.get("urgency_score"), safety_critical)

    return {
        "km_since_service": km_since,
        "days_since_service": days_since,
        "km_overdue": km_overdue,
        "days_overdue": days_overdue,
        "is_overdue": is_overdue,
        "is_safety_critical": safety_critical,
        "km_per_day": round(km_per_day, 1),          # 1 decimal place
        "coe_days_left": coe_days_left,
        "recommended_service_date": service_by.strftime("%d-%m-%Y"),
    }


# ======================================================================
# score -- a number from 0 to 100, used to sort the urgent list
# ======================================================================

def score(record: dict) -> int:
    """Return the risk score (0-100) for one check.
    Used only to sort the urgent list, most serious first; it never changes
    a decision. Returns 0 if the AI gave no urgency score."""
    urgency = record.get("urgency_score")
    if urgency is None:
        return 0

    # Points: urgency x 10, +15 if overdue, +10 if safety-critical, capped at 100.
    facts = evaluate(record)
    total = urgency * 10
    if facts["is_overdue"]:
        total = total + 15
    if facts["is_safety_critical"]:
        total = total + 10
    return min(100, total)        # min(100, ...) caps it at 100


# ======================================================================
# route -- the final decision
# ======================================================================

def route(record: dict) -> str:
    """Decide the final outcome for one check and return it as text,
    e.g. "URGENT - Service immediately"."""
    # The rules are checked top to bottom and the FIRST match wins (each `return`
    # ends the function), so the most serious rules must come first.
    urgency = record.get("urgency_score")
    confidence = record.get("confidence")

    # Rule 1. No valid AI answer: none of the AI-based rules below can be trusted.
    if record.get("ai_status") != "ok" or urgency is None:
        return "NEEDS MANUAL REVIEW - AI assessment unavailable"

    facts = evaluate(record)
    coe_days_left = facts["coe_days_left"]

    # Rule 2. Singapore: an expired COE means the car can't legally be driven,
    # so servicing advice is pointless until the COE is renewed.
    if coe_days_left is not None and coe_days_left < 0:
        return "COE EXPIRED - Renew the COE or deregister before servicing"

    # Rules 3 and 4. MULTI-CONDITION RULE (required by the brief): combines the AI's
    # urgency AND its confidence. A high score is only acted on directly when the
    # AI is sure; otherwise a mechanic should confirm it.
    if urgency >= 8 and confidence == "High":
        return "URGENT - Service immediately"
    if urgency >= 8:
        return "FLAGGED - High urgency but low AI confidence, verify with a mechanic"

    # Rule 5. Safety net: overdue brake pads or tyres are ALWAYS urgent, even if the
    # AI's urgency is low.
    # The wording follows the manual's action, so an overdue brake INSPECTION isn't
    # reported as if the pads themselves must be replaced.
    if facts["is_safety_critical"] and facts["is_overdue"]:
        what = OVERDUE_WORDING.get(record.get("action"), "part")
        return f"URGENT - Safety-critical {what} overdue"

    # Rule 6. COE defer rule: COE ends within 180 days AND not a safety part AND
    # urgency 4 or less -> the service can wait (the car may soon be off the road).
    coe_ends_soon = coe_days_left is not None and coe_days_left <= COE_DEFER_WINDOW_DAYS
    if coe_ends_soon and not facts["is_safety_critical"] and urgency <= 4:
        return "DEFER - COE expires soon, non-critical service can wait"

    # Rules 7 to 9. Everything else: overdue -> DUE SOON, urgency 1-3 -> OK,
    # urgency 4-7 -> MONITOR.
    if facts["is_overdue"]:
        return "DUE SOON - Overdue by manufacturer schedule"
    if urgency <= 3:
        return "OK - Not urgent"
    return "MONITOR - Service approaching"


def is_urgent(record: dict) -> bool:
    """Return True if the saved outcome needs the owner's attention, i.e. it starts
    with one of URGENT_PREFIXES. main.py uses this for menu option 3."""
    outcome = str(record.get("outcome", ""))
    return outcome.startswith(URGENT_PREFIXES)


# ======================================================================
# MAINTENANCE HISTORY RULES
# ======================================================================

def service_sort_key(entry: dict) -> tuple:
    """Sort key for a service entry: (date, odometer). Entries with a damaged date
    sort first, so they are never picked as the latest service."""
    date = to_date(entry.get("service_date")) or datetime.date.min
    odometer = entry.get("service_odometer")
    if not isinstance(odometer, int):
        odometer = -1
    return (date, odometer)


def sort_history(entries: list[dict]) -> list[dict]:
    """Return the service entries newest first (by date, then odometer)."""
    return sorted(entries, key=service_sort_key, reverse=True)


def latest_service(entries: list[dict], part_name: str,
                   scheduled_action: str | None = None) -> dict | None:
    """Return the most recent service of this part, or None if it has never been
    logged. This is the "last service" that an urgency check is based on."""
    for entry in sort_history(entries):
        if entry.get("part_name") == part_name and to_date(entry.get("service_date")):
            action = entry.get("service_action")
            if scheduled_action is not None and action not in (None, "unknown", "replace", scheduled_action):
                continue
            return entry
    return None


def check_service_odometer(entries: list[dict], service_date: str, odometer: int,
                           ignore_id: int | None = None) -> str | None:
    """BUSINESS RULE 1 for the history: an odometer only goes up, so a service on a
    later date can't show fewer km than one on an earlier date (any part counts, as
    the odometer belongs to the whole car). ignore_id skips the entry being edited.
    Returns a message explaining the clash, or None if the reading is consistent."""
    new_date = to_date(service_date)
    if new_date is None:
        return "The service date is not a valid date."
    for entry in entries:
        if ignore_id is not None and entry.get("service_id") == ignore_id:
            continue
        other_date = to_date(entry.get("service_date"))
        other_km = entry.get("service_odometer")
        if other_date is None or not isinstance(other_km, int):
            continue                    # damaged entry: can't compare, skip it
        if other_date < new_date and other_km > odometer:
            return (f"An earlier service ({entry.get('part_name')} on {entry.get('service_date')}) "
                    f"was already at {other_km:,} km, so {odometer:,} km on {service_date} "
                    "would mean the odometer went backwards.")
        if other_date > new_date and other_km < odometer:
            return (f"A later service ({entry.get('part_name')} on {entry.get('service_date')}) "
                    f"was only at {other_km:,} km, so {odometer:,} km on {service_date} "
                    "would mean the odometer went backwards.")
    return None


def latest_check_per_part(records: list[dict]) -> list[dict]:
    """From a car's AI checks (oldest first), keep only the newest check for each part,
    so an old result that has since been re-checked no longer counts as urgent."""
    newest = {}
    for record in records:              # later records overwrite earlier ones
        newest[record.get("part_name")] = record
    return list(newest.values())


def latest_check_for_service(records: list[dict], entry: dict) -> dict | None:
    """Return the newest AI check that was based on this service entry (same part,
    service date and odometer), or None if that service hasn't been checked yet."""
    found = None
    for record in records:
        if (record.get("part_name") == entry.get("part_name")
                and record.get("last_service_date") == entry.get("service_date")
                and record.get("last_service_mileage") == entry.get("service_odometer")):
            found = record              # keep going: a later match is newer
    return found



# ======================================================================
# PLAUSIBILITY RULES FOR WHAT THE USER TYPES
# ======================================================================

def add_years(start: datetime.date, years: int) -> datetime.date:
    """Return the same day `years` years later (29 Feb becomes 28 Feb if needed)."""
    try:
        return start.replace(year=start.year + years)
    except ValueError:                  # 29 Feb in a year that isn't a leap year
        return start.replace(year=start.year + years, day=28)


def coe_date_range(model_year: int | None, today: datetime.date) -> tuple:
    """The COE expiry dates that make sense for a car: not before 1 January of its
    model year (an expired COE is allowed, our rules act on it), and not more than
    COE_MAX_YEARS from today. Returns (earliest, latest); earliest is None if the
    model year is unknown."""
    earliest = datetime.date(model_year, 1, 1) if model_year else None
    return earliest, add_years(today, COE_MAX_YEARS)


def km_pace_problem(from_date, from_km: int, to_date, to_km: int) -> str | None:
    """Check the odometer didn't grow by more than MAX_KM_PER_DAY a day between two
    readings (a same-day pair counts as 1 day). Dates may be date objects or saved
    'DD-MM-YYYY' text. Returns a message if the jump is impossible, else None."""
    start, end = to_date_any(from_date), to_date_any(to_date)
    if start is None or end is None or to_km <= from_km:
        return None                     # nothing to compare, or no growth at all
    days = max(1, (end - start).days)
    if to_km - from_km > MAX_KM_PER_DAY * days:
        return (f"{to_km - from_km:,} km in {days:,} day(s) is more than "
                f"{MAX_KM_PER_DAY:,} km a day, so it looks like a typing mistake.")
    return None


def to_date_any(value) -> datetime.date | None:
    """Accept a date object or saved 'DD-MM-YYYY' text; return a date or None."""
    if isinstance(value, datetime.date):
        return value
    return to_date(value)


def check_service_pace(entries: list[dict], service_date: str, odometer: int,
                       model_year: int | None, ignore_id: int | None = None) -> str | None:
    """A service's odometer must be reachable at MAX_KM_PER_DAY: from 0 km on
    1 January of the model year, and from/to every other service of this car.
    ignore_id skips the entry being edited. Returns a message, or None if fine."""
    if model_year:
        problem = km_pace_problem(datetime.date(model_year, 1, 1), 0, service_date, odometer)
        if problem:
            return f"Since your car's model year began: {problem}"
    for entry in entries:
        if ignore_id is not None and entry.get("service_id") == ignore_id:
            continue
        other_km = entry.get("service_odometer")
        if not isinstance(other_km, int):
            continue
        problem = (km_pace_problem(entry.get("service_date"), other_km, service_date, odometer)
                   or km_pace_problem(service_date, odometer, entry.get("service_date"), other_km))
        if problem:
            return f"Compared with {entry.get('part_name')} on {entry.get('service_date')}: {problem}"
    return None


def max_plausible_odometer(last_date, last_km: int, today: datetime.date) -> int:
    """The highest believable reading today, given the last reading on file:
    last_km + MAX_KM_PER_DAY for each day since then (at least one day)."""
    start = to_date_any(last_date) or today
    days = max(1, (today - start).days)
    return last_km + MAX_KM_PER_DAY * days


def latest_reading(entries: list[dict], checks: list[dict]) -> tuple | None:
    """The car's highest odometer reading on file and its date, from service entries
    and AI checks together. Returns (date_text, km) or None if there is none."""
    readings = []
    for entry in entries:
        if isinstance(entry.get("service_odometer"), int) and to_date(entry.get("service_date")):
            readings.append((entry["service_odometer"], entry["service_date"]))
    for check in checks:
        if isinstance(check.get("current_odometer"), int) and to_date(check.get("check_date")):
            readings.append((check["current_odometer"], check["check_date"]))
    if not readings:
        return None
    km, date_text = max(readings, key=lambda r: (r[0], to_date(r[1])))
    return date_text, km


def find_duplicate_service(entries: list[dict], part_name: str, service_date: str,
                           odometer: int, ignore_id: int | None = None,
                           service_action: str | None = None) -> dict | None:
    """Return an existing entry with the same part, date and odometer (the same service
    typed twice), or None. Compare the performed action when supplied;
    ignore_id skips the entry being edited."""
    for entry in entries:
        if ignore_id is not None and entry.get("service_id") == ignore_id:
            continue
        if (entry.get("part_name") == part_name and entry.get("service_date") == service_date
                and entry.get("service_odometer") == odometer):
            # An inspection and a replacement on one date are different services.
            if service_action is not None and (entry.get("service_action") or "unknown") != service_action:
                continue
            return entry
    return None



# ======================================================================
# WHICH INTERVAL APPLIES ("first at X, then every Y")
# ======================================================================

def choose_interval(rule: dict, part_services: list[dict]) -> dict:
    """Pick the interval that applies to the next service of a part. When the manual
    says 'first at X, then every Y' (rule has repeat_km/repeat_months) and this part
    has already been replaced at least once, the repeat
    interval Y applies; otherwise the first interval X does.
    Returns {"interval_km", "interval_months", "action", "interval_stage"}, where
    interval_stage is "first", "repeat" or None (the manual has only one interval)."""
    chosen = {"interval_km": rule["interval_km"], "interval_months": rule["interval_months"],
              "action": rule.get("action", "replace"), "interval_stage": None}
    if "repeat_km" in rule:
        # Keep legacy records usable, but an explicit inspection is not a replacement.
        replacement_logged = any(service.get("service_action") in (None, "unknown", "replace")
                                 for service in part_services)
        if replacement_logged:
            chosen["interval_km"] = rule["repeat_km"]
            chosen["interval_months"] = rule["repeat_months"]
            chosen["interval_stage"] = "repeat"
        else:
            chosen["interval_stage"] = "first"
    return chosen


def from_new_service(part_name: str, model_year: int) -> dict:
    """A stand-in "last service" for a part that has never been replaced: the car as
    new, at 0 km on 1 January of its model year (the earliest date it can have been
    made). Used for first-change checks such as coolant. It is not saved."""
    return {"service_id": None, "part_name": part_name,
            "service_date": f"01-01-{model_year}", "service_odometer": 0,
            "notes": "from new (never replaced)"}
