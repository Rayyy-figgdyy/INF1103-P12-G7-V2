"""
One service rule from an owner's manual, e.g. Engine Oil: replace every
10,000 km or 12 months. Owned by a Car (composition).
"""
from __future__ import annotations


class PartSchedule:
    """One manufacturer service rule for one part of one car."""

    VALID_ACTIONS = ("replace", "inspect", "rotate")

    def __init__(self, part_name: str, raw: dict):
        # Private attributes (leading underscore): read them through the properties.
        self.__part_name = part_name
        self.__action = raw.get("action", "replace")
        self.__km = raw["km"]
        self.__months = raw["months"]
        self.__repeat_km = raw.get("repeat_km")
        self.__repeat_months = raw.get("repeat_months")
        self.__note = raw.get("note", "")

    @property
    def part_name(self) -> str:
        return self.__part_name

    @property
    def action(self) -> str:
        return self.__action

    @property
    def has_repeat_rule(self) -> bool:
        """True when the manual says 'first at X, then every Y'."""
        return self.__repeat_km is not None

    def as_rule(self) -> dict:
        """The rule in the form the rest of the app uses, e.g.
        {"interval_km": 16000, "interval_months": 12, "action": "replace"}."""
        rule = {"interval_km": self.__km, "interval_months": self.__months,
                "action": self.__action}
        if self.has_repeat_rule:
            rule["repeat_km"] = self.__repeat_km
            rule["repeat_months"] = self.__repeat_months
        return rule

    @staticmethod
    def is_valid_limit_pair(km, months) -> bool:
        """km and months must be whole numbers, 0 or more, at least one above 0
        (0 = the manual gives no limit of that kind)."""
        for value in (km, months):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return False
        return km > 0 or months > 0

    @classmethod
    def is_valid_entry(cls, entry) -> bool:
        """True if a cars.json schedule line is usable, e.g.
        {"action": "replace", "km": 10000, "months": 12}."""
        if not isinstance(entry, dict):
            return False
        if not cls.is_valid_limit_pair(entry.get("km"), entry.get("months")):
            return False
        if entry.get("action", "replace") not in cls.VALID_ACTIONS:
            return False
        if "repeat_km" in entry or "repeat_months" in entry:
            return cls.is_valid_limit_pair(entry.get("repeat_km"), entry.get("repeat_months"))
        return True
