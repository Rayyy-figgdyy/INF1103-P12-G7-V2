"""
logic_manager.py -- the Logic Manager (business rules).

Takes one maintenance check that the AI has already scored and applies our rules:
  - LogicManager.evaluate(): the facts (overdue by km OR time, km/day, COE days left,
    service-by date)
  - LogicManager.score():    a 0-100 risk score, used only to sort the urgent list
  - LogicManager.route():    the final outcome text, decided by a list of OutcomeRule
    objects (includes the urgency + confidence rule)
The rule classes are in logic/rules/, and the history rules in logic/ (one class per
file). All arithmetic is done here, not by the AI. No screen, AI or file access.
"""
from __future__ import annotations

import datetime    # Python's lib for dates

from logic.dates import Dates
from logic.rules.coe_defer_rule import CoeDeferRule
from logic.rules.coe_expired_rule import CoeExpiredRule
from logic.rules.high_urgency_rule import HighUrgencyRule
from logic.rules.low_urgency_rule import LowUrgencyRule
from logic.rules.monitor_rule import MonitorRule
from logic.rules.outcome_rule import OutcomeRule
from logic.rules.overdue_rule import OverdueRule
from logic.rules.safety_overdue_rule import SafetyOverdueRule


class LogicManager:
    """Applies the business rules to one AI-scored check (a record dict).
    AGGREGATION: it holds a list of OutcomeRule objects. They can be passed in (e.g.
    a test's own rules) and exist independently of the manager.
    STRATEGY PATTERN: route() uses every rule through the same outcome() method, so
    a new rule is a new class added to the list; route() is not edited (OCP)."""

    # A failure of these parts is a safety risk (stopping and grip), so they get extra
    # urgency. Lower case so they match part names after .lower().
    SAFETY_CRITICAL_PARTS = ("brake pads", "tyres")
    DAYS_PER_MONTH = 30.44           # average days in a month (so 24 months = 731 days)
    # Kept on the rule classes that use them; repeated here so callers find them.
    COE_DEFER_WINDOW_DAYS = CoeDeferRule.COE_DEFER_WINDOW_DAYS
    OVERDUE_WORDING = SafetyOverdueRule.OVERDUE_WORDING

    # Outcomes for the owner's action: any outcome starting with one of these
    # is in the urgent list (menu option 6)
    URGENT_PREFIXES = ("URGENT", "FLAGGED", "DUE SOON", "COE EXPIRED", "NEEDS MANUAL REVIEW")
    MANUAL_REVIEW = "NEEDS MANUAL REVIEW - AI assessment unavailable"

    def __init__(self, rules: list[OutcomeRule] | None = None):
        # Encapsulation: the rule list is PRIVATE (two underscores, - in UML); a copy
        # is taken so later changes to the caller's list can't change this manager.
        self.__rules = list(rules) if rules is not None else self.default_rules()

    @staticmethod
    def default_rules() -> list[OutcomeRule]:
        """The app's rules in priority order: the most serious come first, because the
        FIRST rule that applies decides the outcome."""
        return [CoeExpiredRule(), HighUrgencyRule(), SafetyOverdueRule(), CoeDeferRule(),
                OverdueRule(), LowUrgencyRule(), MonitorRule()]

    @property
    def rules(self) -> tuple[OutcomeRule, ...]:
        """The rules in use, read-only."""
        return tuple(self.__rules)

    # ---- Business rule 3: the "service by" date ----

    @staticmethod
    def recommend_service_date(check_date: datetime.date, is_overdue: bool,
                               km_left: int | None, days_left: int | None,
                               km_per_day: float, urgency: int | None,
                               safety_critical: bool) -> datetime.date | None:
        """BUSINESS RULE 3: works out the date a part should be serviced by.
        Starts from the schedule's due date, then brings it forward if the AI's
        urgency is high. Returns a recommended date, or None when there is no
        limit to count down and no high urgency (no evidence for a date)."""
        # ---- Part A: the schedule's due date ----
        if is_overdue:
            due = check_date
        else:
            # Due when either time limit runs out or KM limit at the rate the driver drives.
            # int() will round down so the date will recommend early rather than late
            possible_dates = []
            if days_left is not None:
                possible_dates.append(Dates.add_days(check_date, days_left))
            if km_left is not None and km_per_day > 0:
                days_until_km_limit = int(km_left / km_per_day)
                possible_dates.append(Dates.add_days(check_date, days_until_km_limit))
            if possible_dates:
                due = min(possible_dates)       # min = the earliest date
            else:
                due = None

        # ---- Part B: High AI urgency can bring it forward ----
        # Urgency 8-10: within 3 days. Urgency 5-7: within 14 days. 1-4: date from part A.
        if urgency is not None and urgency >= 8:
            days_allowed = 3
        elif urgency is not None and urgency >= 5:
            days_allowed = 14
        else:
            days_allowed = None                 # low urgency: stick to Part A date

        if days_allowed is not None:
            if safety_critical:
                # Brake pads and tyres get half the time (3 -> 1 day, 14 -> 7 days),
                # never less than 1 day.
                days_allowed = max(1, days_allowed // 2)
            # min(): Taking the earlier date means urgency can only bring date forward but never
            # push it back
            urgent_date = Dates.add_days(check_date, days_allowed)
            due = min(due, urgent_date) if due is not None else urgent_date

        return due

    # ---- evaluate: the facts about one check ----

    def evaluate(self, record: dict) -> dict:
        """Work out the facts about one check: km and days since the last service,
        whether it's overdue, how far the owner drives a day, whether it's a
        safety-critical part, days left on the COE, and the service-by date.
        These come back as a new dictionary; the record itself isn't changed."""

        # ---- The dates ----
        # No check date means using todays date; missing last-service date means 0 days since service..
        check_date = Dates.to_date(record.get("check_date")) or datetime.date.today()
        last_service_date = Dates.to_date(record.get("last_service_date")) or check_date

        # ---- The stored schedule (business rule 2) ----
        # Intervals always come from our schedules in car.json, never from the AI.
        interval_km = int(record.get("interval_km") or 0)
        interval_days = round((record.get("interval_months") or 0) * self.DAYS_PER_MONTH)

        # ---- How far, and how long, since the last service ----
        # max(0, ...) stops invalid data such as negative from going through
        odometer_now = int(record.get("current_odometer") or 0)
        odometer_at_service = int(record.get("last_service_mileage") or 0)
        km_since = max(0, odometer_now - odometer_at_service)
        days_since = max(0, (check_date - last_service_date).days)

        # ---- Is it overdue? (by distance, by time, or both) ----
        # Manual says overdue when "10,000 km or 12 months" so reaching either limit works
        # A limit of 0 means the part has no such limit in the manual.
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

        # ---- Is it a safety-critical part? ----
        part = str(record.get("part_name", "")).strip().lower()
        safety_critical = part in self.SAFETY_CRITICAL_PARTS

        # ---- Days until COE expires (negative means already expired)----
        coe_date = Dates.to_date(record.get("coe_expiry_date"))
        if coe_date is not None:
            coe_days_left = (coe_date - check_date).days
        else:
            coe_days_left = None

        # ---- Business rule 3: the "service by" date ----
        service_by = self.recommend_service_date(check_date, is_overdue, km_left, days_left,
                                                 km_per_day, record.get("urgency_score"),
                                                 safety_critical)

        return {
            "km_since_service": km_since,
            "days_since_service": days_since,
            "km_overdue": km_overdue,
            "days_overdue": days_overdue,
            "is_overdue": is_overdue,
            "is_safety_critical": safety_critical,
            "km_per_day": round(km_per_day, 1),          # 1 decimal place
            "coe_days_left": coe_days_left,
            # "N/A" is clearer than inventing today's date without driving evidence.
            "recommended_service_date": (service_by.strftime(Dates.DATE_FORMAT)
                                         if service_by else "N/A"),
        }

    # ---- score: 0-100, used to sort the urgent list ----

    def score(self, record: dict) -> int:
        """Give one check a risk score from 0 to 100.
        Only used to put the most serious items at the top of the urgent list;
         Never changes outcome. A check with no AI urgency scores 0"""
        urgency = record.get("urgency_score")
        if urgency is None:
            return 0

        # Points: urgency x 10, +15 if overdue, +10 if safety-critical, capped at 100.
        facts = self.evaluate(record)
        total = urgency * 10
        if facts["is_overdue"]:
            total = total + 15
        if facts["is_safety_critical"]:
            total = total + 10
        return min(100, total)        # never more than 100

    # ---- route: the final decision ----

    def route(self, record: dict) -> str:
        """Decide the final outcome for one check and return it as text,
        e.g. "URGENT - Service immediately"."""
        # No valid AI answer: none of the AI-based rules can be trusted, so this check
        # comes first, before any facts are worked out.
        if record.get("ai_status") != "ok" or record.get("urgency_score") is None:
            return self.MANUAL_REVIEW

        # POLYMORPHISM: each rule object answers outcome() in its own way. The rules
        # are tried in order and the FIRST one that applies (not None) wins.
        facts = self.evaluate(record)
        for rule in self.__rules:
            result = rule.outcome(record, facts)
            if result is not None:
                return result
        # Only reachable with a custom rule list that has no catch-all rule.
        return MonitorRule.OUTCOME

    def is_urgent(self, record: dict) -> bool:
        """Return True if the saved outcome needs the owner's attention, i.e. it starts
        with one of URGENT_PREFIXES. Used for menu option 3."""
        outcome = str(record.get("outcome", ""))
        return outcome.startswith(self.URGENT_PREFIXES)
