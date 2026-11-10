"""
A supported car with its manual and service schedule. COMPOSITION: a Car
creates and owns its PartSchedule objects.
"""
from __future__ import annotations

from models.part_schedule import PartSchedule


class Car:
    """A supported car model with its manual and its service schedule.
    Composition: the PartSchedule objects are created here and owned by the Car."""

    VALID_CONDITIONS = ("Brand New", "Used")

    def __init__(self, model: str, condition: str, manual: str,
                 schedule: dict, year: int | None = None, schedule_source: str = ""):
        self.__model = model
        self.__condition = condition
        self.__manual = manual
        self.__year = year if isinstance(year, int) and not isinstance(year, bool) else None
        self.__schedule_source = schedule_source
        # Composition: each valid schedule line becomes a PartSchedule owned by this
        # Car. An invalid line is left out, so that part simply isn't offered.
        self.__parts = {}
        for part_name, raw in schedule.items():
            if PartSchedule.is_valid_entry(raw):
                self.__parts[part_name] = PartSchedule(part_name, raw)

    @property
    def model(self) -> str:
        return self.__model

    @property
    def condition(self) -> str:
        return self.__condition

    @property
    def manual(self) -> str:
        """The manual's path relative to the project folder."""
        return self.__manual

    @property
    def model_year(self) -> int | None:
        """The model year from cars.json, else a 4-digit year ending the model name."""
        if self.__year is not None:
            return self.__year
        words = self.__model.split()
        last_word = words[-1] if words else ""
        if last_word.isdigit() and len(last_word) == 4:
            return int(last_word)
        return None

    def part_names(self) -> list[str]:
        """The parts with a stored rule, A-Z."""
        return sorted(self.__parts)

    def schedule_for(self, part_name: str) -> PartSchedule | None:
        return self.__parts.get(part_name)

    @staticmethod
    def is_valid_entry(raw) -> bool:
        """True if a cars.json car entry has a model, a valid condition, a manual path
        and a schedule."""
        return (isinstance(raw, dict)
                and isinstance(raw.get("model"), str) and raw["model"].strip() != ""
                and raw.get("condition") in Car.VALID_CONDITIONS
                and isinstance(raw.get("manual"), str)
                and isinstance(raw.get("schedule"), dict))

    @classmethod
    def from_dict(cls, raw: dict) -> Car:
        """Build a Car from one validated cars.json entry."""
        return cls(raw["model"], raw["condition"], raw["manual"], raw["schedule"],
                   raw.get("year"), raw.get("schedule_source", ""))
