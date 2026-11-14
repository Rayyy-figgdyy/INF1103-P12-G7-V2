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
from storage.repository_factory import RepositoryFactory
from storage.json_store import JsonStore
from storage.service_history_repository import ServiceHistoryRepository
from storage.user_repository import UserRepository


class DataManager:
    """One object that gives the rest of the app everything in the Data layer.
    COMPOSITION: it creates its four parts (and their repositories) itself, for one
    data folder, and they live and die with it; they are only reachable through the
    read-only properties below. AGGREGATION: it is given a RepositoryFactory, which
    decides whether records go to JSON files or MongoDB (the JSON files by default).
    Tests pass a temporary data_dir so the real data/ folder is never touched."""

    HISTORY_FILENAME = "maintenance_history.json"
    CHECKS_FILENAME = "prompt_records.json"
    USERS_FILENAME = "users.json"
    CARS_FILENAME = "cars.json"

    def __init__(self, data_dir: str | None = None, project_dir: str | None = None,
                 repositories: RepositoryFactory | None = None):
        # Paths are built from this file's location, so the app finds data/ whatever
        # folder it is started from (including inside Docker).
        if project_dir is None:
            project_dir = os.path.dirname(os.path.abspath(__file__))
        if data_dir is None:
            data_dir = os.path.join(project_dir, "data")
        self.__data_dir = data_dir
        # PROTECTED (#): FuelDataManager uses the same factory for its repositories.
        self._repositories = repositories or RepositoryFactory()

        self.__users = UserRepository(
            self._repositories.create(os.path.join(data_dir, self.USERS_FILENAME)))
        self.__history = ServiceHistoryRepository(
            self._repositories.create(os.path.join(data_dir, self.HISTORY_FILENAME)))
        self.__checks = CheckRepository(
            self._repositories.create(os.path.join(data_dir, self.CHECKS_FILENAME)))
               # The car list stays a JSON file: it is reference data from the manuals.
        self.__cars = CarCatalogue(
            JsonStore(os.path.join(data_dir, self.CARS_FILENAME)), project_dir)

    @property
    def data_dir(self) -> str:
        return self.__data_dir

    @property
    def storage_name(self) -> str:
        """Where the records are kept, e.g. "JSON files" or "MongoDB (...)"."""
        return self._repositories.storage_name

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
        saved_records = (self.__checks.for_plate(license_plate)+ self.__history.for_plate(license_plate))         
        
        return CheckRepository.last_odometer(saved_records, license_plate)
