"""
data_manager.py -- the Data Manager: saves and loads everything the app remembers.

Four JSON files in data/:
    maintenance_history.json   the services each owner has had done (their service log)
    prompt_records.json        every AI urgency check, also used to spot repeated input
    users.json                 user profiles, one per license plate
    cars.json                  the 4 supported cars and their service schedules
The classes that do the work are in storage/ (one class per file). Only saving,
loading and lookups here: no business decisions and no print().
"""
from __future__ import annotations

import os

from storage.car_catalogue import CarCatalogue
from storage.check_repository import CheckRepository
from storage.json_repository import JsonRepository
from storage.json_store import JsonStore
from storage.service_history_repository import ServiceHistoryRepository
from storage.user_repository import UserRepository


class DataManager:
    """One object that gives the rest of the app everything in the Data layer.
    COMPOSITION: it creates its four parts (and their repositories) itself, for one
    data folder, and they live and die with it; they are only reachable through the
    read-only properties below.
    Tests pass a temporary data_dir so the real data/ folder is never touched."""

    HISTORY_FILENAME = "maintenance_history.json"
    CHECKS_FILENAME = "prompt_records.json"
    USERS_FILENAME = "users.json"
    CARS_FILENAME = "cars.json"

    def __init__(self, data_dir: str | None = None, project_dir: str | None = None):
        # Paths are built from this file's location, so the app finds data/ whatever
        # folder it is started from (including inside Docker).
        if project_dir is None:
            project_dir = os.path.dirname(os.path.abspath(__file__))
        if data_dir is None:
            data_dir = os.path.join(project_dir, "data")
        self.__data_dir = data_dir

        self.__users = UserRepository(
            JsonRepository(os.path.join(data_dir, self.USERS_FILENAME)))
        self.__history = ServiceHistoryRepository(
            JsonRepository(os.path.join(data_dir, self.HISTORY_FILENAME)))
        self.__checks = CheckRepository(
            JsonRepository(os.path.join(data_dir, self.CHECKS_FILENAME)))
        self.__cars = CarCatalogue(
            JsonStore(os.path.join(data_dir, self.CARS_FILENAME)), project_dir)

    @property
    def data_dir(self) -> str:
        return self.__data_dir

    @property
    def users(self) -> UserRepository:
        return self.__users

    @property
    def history(self) -> ServiceHistoryRepository:
        return self.__history

    @property
    def checks(self) -> CheckRepository:
        return self.__checks

    @property
    def cars(self) -> CarCatalogue:
        return self.__cars

    def last_odometer_on_file(self, license_plate: str) -> int | None:
        """The highest odometer reading saved for this car, from its AI checks and its
        service log together (None if there is none)."""
        saved_records = self.__checks.load() + self.__history.load_all()
        return CheckRepository.last_odometer(saved_records, license_plate)
