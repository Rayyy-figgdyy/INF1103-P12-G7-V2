"""
The supported cars from data/cars.json, as Car objects. Business rule 2:
service intervals come only from here, never from the user or the AI.
"""
from __future__ import annotations

import logging
import os

from models.car import Car
from storage.json_store import JsonStore

# Logged under the Data Manager's name, so its messages read "data_manager: ...".
logger = logging.getLogger("data_manager")


class CarCatalogue:
    """The supported cars, read from cars.json as Car objects. AGGREGATION: it is
    given the JsonStore for cars.json. Each Car in turn OWNS its PartSchedule
    objects (composition, see models/car.py)."""

    def __init__(self, store: JsonStore, project_dir: str):
        self.__store = store
        self.__project_dir = project_dir     # manual paths in cars.json are relative to it

    def load_cars(self) -> list[Car]:
        """Return every valid car from cars.json, in file order. An invalid car is
        logged and skipped; an invalid schedule line is dropped silently by Car, so that
        part just isn't offered. Returns [] if the file is missing, damaged or has no
        "cars" list. The file is re-read on every call, so edits show up at once."""
        data = self.__store.read()
        if not isinstance(data, dict) or not isinstance(data.get("cars"), list):
            if data is not None:
                logger.error("%s has no 'cars' list.", self.__store.path)
            return []

        cars = []
        for raw in data["cars"]:
            # An invalid car is skipped and logged; the other cars still load.
            if not Car.is_valid_entry(raw):
                logger.error("Skipping invalid car entry in %s: %r", self.__store.path, raw)
                continue
            cars.append(Car.from_dict(raw))
        return cars

    def list_models(self) -> list[str]:
        """Return the car model names to choose from at registration, in file order."""
        return [car.model for car in self.load_cars()]

    def find(self, car_model: str) -> Car | None:
        """Return the Car with this exact model name, or None."""
        for car in self.load_cars():
            if car.model == car_model:
                return car
        return None

    def list_parts(self, car_model: str) -> list[str]:
        """Return the part names in this car's schedule, A-Z ([] if the car is unknown)."""
        car = self.find(car_model)
        if car is None:
            return []
        return car.part_names()

    def get_service_interval(self, car_model: str, part_name: str) -> dict | None:
        """Return the stored rule for this car and part, e.g.
        {"interval_km": 10000, "interval_months": 12, "action": "replace"}, plus
        "repeat_km"/"repeat_months" when the manual says 'first at X, then every Y'.
        Returns None if the car or part is unknown."""
        car = self.find(car_model)
        if car is None:
            return None
        schedule = car.schedule_for(part_name)
        if schedule is None:
            return None
        return schedule.as_rule()

    def get_model_year(self, car_model: str) -> int | None:
        """Return the car's model year, e.g. 2020: the "year" in cars.json, or else a
        4-digit year at the end of the model name. None if neither is there."""
        car = self.find(car_model)
        if car is not None:
            return car.model_year
        # Unknown car: the model name is the only clue.
        words = car_model.split()
        last_word = words[-1] if words else ""
        if last_word.isdigit() and len(last_word) == 4:
            return int(last_word)
        return None

    def get_manual_path(self, car_model: str) -> str | None:
        """Return the full path to this car's manual PDF, or None if the car is unknown
        or the file isn't there (a missing file is logged)."""
        car = self.find(car_model)
        if car is None:
            return None
        path = os.path.join(self.__project_dir, car.manual)
        if not os.path.isfile(path):
            logger.error("Manual for %s not found at %s", car_model, path)
            return None
        return path
