"""
Checks brake-pad history before it may be sent to the AI.
"""
from __future__ import annotations

import datetime

from logic.dates import Dates
from logic.history_rules import HistoryRules


class BrakeHistoryAnalyser:
    """Checks brake-pad history before the AI analyses it (it does not calculate the
    replacement intervals itself). AGGREGATION: it is given a HistoryRules object that
    is created elsewhere and shared, so the same odometer/pace rules are applied
    everywhere, and a different HistoryRules (e.g. in a test) can be swapped in."""

    MIN_REPLACEMENTS = 3

    def __init__(self, rules: HistoryRules):
        self.__rules = rules

    def context(self, entries: list[dict], model_year: int | None,
                check_date: datetime.date, current_odometer: int) -> dict:
        """Check whether the car's brake pad history is reliable enough to show the AI.
        We don't calculate the gaps between replacements here; we only make sure the
        records make sense. If there are at least 3 separate confirmed replacements and
        nothing looks wrong, the AI gets those replacements and works out the pattern.
        Returns {"eligible", "replacement_count", "reason", "replacement_records"}."""
        clean = []
        unreliable = None
        earliest = datetime.date(model_year, 1, 1) if model_year is not None else None

        # ---- Step 1: keep only brake-pad entries with usable dates, km and actions ----
        for entry in entries:
            if entry.get("part_name") != "Brake Pads":
                continue
            date = Dates.to_date(entry.get("service_date"))
            odometer = entry.get("service_odometer")
            if (date is None or date > check_date or (earliest is not None and date < earliest)
                    or not isinstance(odometer, int) or isinstance(odometer, bool)
                    or odometer < 0 or odometer > current_odometer):
                unreliable = unreliable or "Brake-pad history contains invalid dates or odometer readings."
                continue
            if entry.get("service_action") not in (None, "unknown", "inspect", "replace"):
                unreliable = unreliable or "Brake-pad history contains an invalid performed action."
                continue
            clean.append(entry)

        # ---- Step 2: each entry must pass the history rules; collect replacements ----
        replacements = []
        seen = set()
        for entry in clean:
            date = entry["service_date"]
            odometer = entry["service_odometer"]
            problem = (self.__rules.check_service_odometer(clean, date, odometer)
                       or self.__rules.check_service_pace(clean, date, odometer, model_year)
                       or self.__rules.km_pace_problem(date, odometer, check_date, current_odometer))
            if problem is not None:
                unreliable = unreliable or problem
                continue
            if entry.get("service_action") == "replace":
                key = (date, odometer)
                if key not in seen:
                    seen.add(key)
                    replacements.append({
                        "service_date": date,
                        "service_odometer": odometer,
                        "service_action": "replace",
                    })

        replacements = sorted(replacements, key=lambda item: (Dates.to_date(item["service_date"]),
                                                                item["service_odometer"]))
        count = len(replacements)
        reason = unreliable or ("" if count >= self.MIN_REPLACEMENTS else
                                "At least three distinct confirmed replacements are needed.")
        return {
            "eligible": count >= self.MIN_REPLACEMENTS and unreliable is None,
            "replacement_count": count,
            "reason": reason,
            "replacement_records": replacements,
        }
