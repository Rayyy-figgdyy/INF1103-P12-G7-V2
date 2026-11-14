"""
FACTORY PATTERN (Week 11): RepositoryFactory decides where records are kept -- JSON files
in data/ or MongoDB collections -- so DataManager never needs to know (open/closed
principle). Set in .env:  STORAGE=mongo  MONGODB_URI=...  MONGODB_DATABASE=...
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

from storage.json_repository import JsonRepository
from storage.mongo_connection import MongoConnection
from storage.mongo_repository import MongoRepository
from storage.repository import Repository

# Logged under the Data Manager's name, so its messages read "data_manager: ...".
logger = logging.getLogger("data_manager")


class RepositoryFactory:
    """Creates one Repository per data file. AGGREGATION: it is given the
    MongoConnection (None = use the JSON files)."""

    DEFAULT_DATABASE = "car_maintenance_tracker"

    def __init__(self, connection: MongoConnection | None = None):
        self.__connection = connection

    @property
    def uses_mongo(self) -> bool:
        return self.__connection is not None

    @property
    def storage_name(self) -> str:
        """Where the records are kept, for the screens: e.g. "MongoDB (car_...)"."""
        if self.__connection is None:
            return "JSON files"
        return f"MongoDB ({self.__connection.database_name})"

    def create(self, path: str) -> Repository:
        """A Repository for one data file's records. With MongoDB, the collection is
        named after the file: data/users.json -> the "users" collection."""
        if self.__connection is None:
            return JsonRepository(path)
        name = os.path.splitext(os.path.basename(path))[0]
        return MongoRepository(self.__connection.collection(name))

    @classmethod
    def from_env(cls) -> RepositoryFactory:
        """Read the storage settings from .env. STORAGE=mongo connects to MongoDB; if
        that is not possible, the JSON files are used and a warning is logged."""
        load_dotenv()
        if os.environ.get("STORAGE", "json").strip().lower() != "mongo":
            return cls()
        uri = os.environ.get("MONGODB_URI", "").strip()
        if not uri:
            logger.warning("STORAGE=mongo but MONGODB_URI is not set -- using the JSON files.")
            return cls()
        database = os.environ.get("MONGODB_DATABASE", "").strip() or cls.DEFAULT_DATABASE
        connection = MongoConnection.connect(uri, database)
        if connection is None:
            logger.warning("MongoDB is unavailable -- using the JSON files instead.")
            return cls()
        return cls(connection)