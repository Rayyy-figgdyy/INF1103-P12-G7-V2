"""
JsonToMongoImporter: copies the records in data/*.json into MongoDB once, so a team
member's existing JSON data is still there after switching to STORAGE=mongo.
Run from the project folder:  python -m storage.json_to_mongo_importer [--overwrite]
"""
from __future__ import annotations

import logging
import os
import sys

from storage.fuel_data_manager import FuelDataManager
from storage.json_repository import JsonRepository
from storage.repository_factory import RepositoryFactory

logger = logging.getLogger("data_manager")


class JsonToMongoImporter:
    """AGGREGATION: it is given the RepositoryFactory that points at MongoDB.
    A collection that already has records is skipped unless overwrite is True, so
    running it twice never duplicates or loses data. The car list stays a JSON file."""

    FILENAMES = (FuelDataManager.USERS_FILENAME, FuelDataManager.HISTORY_FILENAME,
                 FuelDataManager.CHECKS_FILENAME, FuelDataManager.FUEL_FILENAME,
                 FuelDataManager.FUEL_ASSESSMENT_FILENAME, FuelDataManager.FUEL_REVIEW_FILENAME)

    def __init__(self, repositories: RepositoryFactory, data_dir: str):
        self.__repositories = repositories
        self.__data_dir = data_dir

    def run(self, overwrite: bool = False) -> int:
        """Import every file; returns how many records were copied."""
        copied = 0
        for filename in self.FILENAMES:
            path = os.path.join(self.__data_dir, filename)
            records = JsonRepository(path).load_all()
            target = self.__repositories.create(path)
            if target.load_all() and not overwrite:
                logger.warning("Skipped %s: MongoDB already has these records "
                               "(use --overwrite to replace them).", filename)
            elif target.save_all(records):
                logger.info("Imported %d record(s) from %s.", len(records), filename)
                copied += len(records)
            else:
                logger.error("Could not import %s.", filename)
        return copied


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    factory = RepositoryFactory.from_env()
    if not factory.uses_mongo:
        logger.error("MongoDB is not connected: check STORAGE=mongo and MONGODB_URI in .env.")
        sys.exit(1)
    JsonToMongoImporter(factory, FuelDataManager().data_dir).run("--overwrite" in sys.argv)