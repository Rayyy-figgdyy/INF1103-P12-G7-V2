"""
Business rules for the maintenance history and for readings the user types:
the latest service, odometer readings that never go backwards (business
rule 1), duplicates, the km-per-day limit and the COE date range.
"""
from __future__ import annotations

import datetime

from logic.dates import Dates


class HistoryRules:
    """Rules for the service history and for readings the user types (SRP: history
    and plausibility only; routing lives in LogicManager). Service entries and AI
    checks stay plain dicts, as saved in the JSON files."""

    # Plausibility for odometer input; even heavy drivers unlikely to drive past this amount,
    # so any input past this amount is considered an error
    MAX_KM_PER_DAY = 2_000

    # COE Validation (Not more than 10 years expiry from previous date)
    COE_MAX_YEARS = 10

    # ---- Ordering the history ----

    @staticmethod
    def service_sort_key(entry: dict) -> tuple:
        """Sorts service entries by: date, then odometer. A Broken
        date goes to the very start, so it's never picked as the latest service."""
        date = Dates.to_date(entry.get("service_date")) or datetime.date.min
        odometer = entry.get("service_odometer")
        if not isinstance(odometer, int):
            odometer = -1
        return (date, odometer)

    def sort_history(self, entries: list[dict]) -> list[dict]:
        """Return the service entries by newest first (by date, then odometer)."""
        return sorted(entries, key=self.service_sort_key, reverse=True)

    def latest_service(self, entries: list[dict], part_name: str,
                       scheduled_action: str | None = None,
                       model_year: int | None = None) -> dict | None:
        """Return the most recent service of this part, or None if it has never been
        logged. This is the "last service" that an urgency check is based on."""
        for entry in self.sort_history(entries):
            service_date = Dates.to_date(entry.get("service_date"))
            odometer = entry.get("service_odometer")
            if (entry.get("part_name") == part_name and service_date
                    and service_date <= datetime.date.today()
                    and (model_year is None or service_date >= datetime.date(model_year, 1, 1))
                    and isinstance(odometer, int) and not isinstance(odometer, bool)
                    and odometer >= 0):
                action = entry.get("service_action")
                # Unknown legacy actions cannot prove an inspection or replacement.
                # A confirmed replacement can also reset an inspection/rotation interval.
                if scheduled_action is not None and action not in ("replace", scheduled_action):
                    continue
                return entry
        return None

    def check_service_odometer(self, entries: list[dict], service_date: str, odometer: int,
                               ignore_id: int | None = None) -> str | None:
        """BUSINESS RULE 1 for the history: an odometer only goes up, so a later service
        can't show fewer km than an earlier one. Every part counts, because the odometer
        belongs to the whole car. ignore_id skips the entry being edited.
        Gives back a message explaining the problem, or None if the reading fits."""
        new_date = Dates.to_date(service_date)
        if new_date is None:
            return "The service date is not a valid date."
        for entry in entries:
            if ignore_id is not None and entry.get("service_id") == ignore_id:
                continue
            other_date = Dates.to_date(entry.get("service_date"))
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

    # ---- Matching AI checks to the history ----

    @staticmethod
    def latest_check_per_part(records: list[dict]) -> list[dict]:
        """From a car's AI checks (oldest first), keep only the newest check for each part,
        so an old result that has since been re-checked no longer counts as urgent."""
        newest = {}
        for record in records:              # later records overwrite earlier ones
            newest[record.get("part_name")] = record
        return list(newest.values())

    @staticmethod
    def is_check_superseded(record: dict, history: list[dict]) -> bool:
        """True when a newer relevant maintenance action makes an old check outdated.
        Compare service dates AND odometers so we do not hide unrelated old checks.
        An inspection does not reset a manufacturer's replacement schedule."""
        baseline_date = Dates.to_date(record.get("last_service_date"))
        baseline_km = record.get("last_service_mileage")
        if baseline_date is None or not isinstance(baseline_km, int):
            return False

        # A check tied to a particular service ID is stale if that entry was edited
        # or deleted. This also finds changes that do not increase the odometer.
        service_id = record.get("service_id")
        if service_id is not None:
            matching = next((item for item in history
                             if item.get("service_id") == service_id), None)
            if matching is None:
                return True
            if (matching.get("service_date") != record.get("last_service_date")
                    or matching.get("service_odometer") != baseline_km
                    or (matching.get("service_action") or "unknown") !=
                    (record.get("last_service_action") or "unknown")):
                return True

        required_action = record.get("action", "replace")
        for service in history:
            if service.get("part_name") != record.get("part_name"):
                continue
            action = service.get("service_action")
            # A confirmed replacement also satisfies a scheduled inspection.
            if action not in ("replace", required_action):
                continue
            service_date = Dates.to_date(service.get("service_date"))
            service_km = service.get("service_odometer")
            if service_date is None or not isinstance(service_km, int):
                continue
            if service_date > baseline_date or (
                service_date == baseline_date and service_km > baseline_km
            ):
                return True
        return False

    @staticmethod
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

    # ---- Plausibility rules for what the user types ----

    def coe_date_range(self, model_year: int | None, today: datetime.date) -> tuple:
        """The range of COE expiry dates that make sense for a car: no earlier than
        1 January of its model year, and no more than COE_MAX_YEARS from today. A date
        that has already passed is fine, because our rules handle an expired COE.
        Gives back (earliest, latest); earliest is None if we don't know the model year."""
        earliest = datetime.date(model_year, 1, 1) if model_year else None
        return earliest, Dates.add_years(today, self.COE_MAX_YEARS)

    def km_pace_problem(self, from_date, from_km: int, to_date, to_km: int) -> str | None:
        """Check the odometer didn't go up by more than MAX_KM_PER_DAY a day between two
        readings (two readings on the same day count as 1 day apart). The dates can be
        date objects or saved 'DD-MM-YYYY' text. Gives back a message if the jump is
        impossible, or None if it's fine."""
        start, end = Dates.to_date_any(from_date), Dates.to_date_any(to_date)
        if start is None or end is None or to_km <= from_km:
            return None                     # nothing to compare, or no growth at all
        days = max(1, (end - start).days)
        if to_km - from_km > self.MAX_KM_PER_DAY * days:
            return (f"{to_km - from_km:,} km in {days:,} day(s) is more than "
                    f"{self.MAX_KM_PER_DAY:,} km a day, so it looks like a typing mistake.")
        return None

    def check_service_pace(self, entries: list[dict], service_date: str, odometer: int,
                           model_year: int | None, ignore_id: int | None = None) -> str | None:
        """Checks if a service's odometer is reachable at MAX_KM_PER_DAY: from 0 km on
        1 January of the model year, compared with every other service of this car.
        ignore_id skips the entry being edited. Returns a message, or None if fine."""
        if model_year:
            problem = self.km_pace_problem(datetime.date(model_year, 1, 1), 0,
                                           service_date, odometer)
            if problem:
                return f"Since your car's model year began: {problem}"
        for entry in entries:
            if ignore_id is not None and entry.get("service_id") == ignore_id:
                continue
            other_km = entry.get("service_odometer")
            if not isinstance(other_km, int):
                continue
            problem = (self.km_pace_problem(entry.get("service_date"), other_km,
                                            service_date, odometer)
                       or self.km_pace_problem(service_date, odometer,
                                               entry.get("service_date"), other_km))
            if problem:
                return f"Compared with {entry.get('part_name')} on {entry.get('service_date')}: {problem}"
        return None

    def max_plausible_odometer(self, last_date, last_km: int, today: datetime.date) -> int:
        """The highest possible reading today, given the last reading on file:
        last reading on file + MAX_KM_PER_DAY for each day since then (at least one day)."""
        start = Dates.to_date_any(last_date) or today
        days = max(1, (today - start).days)
        return last_km + self.MAX_KM_PER_DAY * days

    @staticmethod
    def latest_reading(entries: list[dict], checks: list[dict]) -> tuple | None:
        """Find the car's highest odometer reading on file and its date, looking at both
        the service history and the AI checks. Gives back (date_text, km), or None if
        there are no readings yet."""
        readings = []
        for entry in entries:
            if isinstance(entry.get("service_odometer"), int) and Dates.to_date(entry.get("service_date")):
                readings.append((entry["service_odometer"], entry["service_date"]))
        for check in checks:
            if isinstance(check.get("current_odometer"), int) and Dates.to_date(check.get("check_date")):
                readings.append((check["current_odometer"], check["check_date"]))
        if not readings:
            return None
        km, date_text = max(readings, key=lambda r: (r[0], Dates.to_date(r[1])))
        return date_text, km

    @staticmethod
    def find_duplicate_service(entries: list[dict], part_name: str, service_date: str,
                               odometer: int, ignore_id: int | None = None,
                               service_action: str | None = None) -> dict | None:
        """Look for an existing entry with the same part, date and odometer, which means
        the same service was typed in twice. If service_action is given, it has to match
        too. ignore_id skips the entry being edited. Gives back the match, or None."""
        for entry in entries:
            if ignore_id is not None and entry.get("service_id") == ignore_id:
                continue
            if (entry.get("part_name") == part_name and entry.get("service_date") == service_date
                    and entry.get("service_odometer") == odometer):
                # An inspection and a replacement on one date are different services.
                if (service_action is not None
                        and (entry.get("service_action") or "unknown") != service_action):
                    continue
                return entry
        return None

    # ---- Which interval applies ("first at X, then every Y") ----

    @staticmethod
    def choose_interval(rule: dict, part_services: list[dict]) -> dict:
        """Picks an interval according to the manual. Some manuals have a first change
        interval and another interval for subsequent changes. This checks which one is
        applicable."""
        chosen = {"interval_km": rule["interval_km"], "interval_months": rule["interval_months"],
                  "action": rule.get("action", "replace"), "interval_stage": None}
        if "repeat_km" in rule:
            # Inspections and unconfirmed legacy records do not start the repeat cycle.
            replacement_logged = any(service.get("service_action") == "replace"
                                     for service in part_services)
            if replacement_logged:
                chosen["interval_km"] = rule["repeat_km"]
                chosen["interval_months"] = rule["repeat_months"]
                chosen["interval_stage"] = "repeat"
            else:
                chosen["interval_stage"] = "first"
        return chosen

    @staticmethod
    def from_new_service(part_name: str, model_year: int) -> dict:
        """A stand-in "last service" for a part that has never been replaced, so we can
        count from when the car was new: 0 km on 1 January of its model year (if exact build date
        is unknown). Used for first-change checks such as coolant.
        It is never saved to the history."""
        return {"service_id": None, "part_name": part_name,
                "service_date": f"01-01-{model_year}", "service_odometer": 0,
                "notes": "from new (never replaced)"}
