"""
MongoRepository: a Repository kept in one MongoDB collection. Each operation is one
MongoDB query, e.g. find({"license_plate": ...}) or delete_many(...). A database error is
logged and gives the same "nothing found / not saved" answer as the JSON files.
"""
from __future__ import annotations

import logging

from pymongo.errors import PyMongoError

from storage.repository import Repository

# Logged under the Data Manager's name, so its messages read "data_manager: ...".
logger = logging.getLogger("data_manager")


class MongoRepository(Repository):
    """Implements the Repository INTERFACE with MongoDB queries, so it can stand in for
    a JsonRepository anywhere (Liskov substitution). AGGREGATION: it is given its
    collection by MongoConnection."""

    HIDE_ID = {"_id": 0}            # MongoDB's own _id field is never given to the app
    SAVED_ORDER = ("_id", 1)        # _id grows over time, so this is the order saved

    def __init__(self, collection):
        self.__collection = collection

    def load_all(self) -> list[dict]:
        return self.find({})

    def save_all(self, items: list[dict]) -> bool:
        """Replace the whole collection (used by the JSON importer)."""
        try:
            self.__collection.delete_many({})
            records = [dict(item) for item in items if isinstance(item, dict)]
            if records:
                self.__collection.insert_many(records)
            return True
        except PyMongoError as error:
            self.__log("save", error)
            return False

    def find(self, criteria: dict) -> list[dict]:
        try:
            return list(self.__collection.find(criteria, self.HIDE_ID).sort(*self.SAVED_ORDER))
        except PyMongoError as error:
            self.__log("read", error)
            return []

    def insert(self, record: dict) -> bool:
        try:
            self.__collection.insert_one(dict(record))   # a copy: MongoDB adds _id to it
            return True
        except PyMongoError as error:
            self.__log("insert", error)
            return False

    def replace(self, criteria: dict, record: dict, upsert: bool = False) -> bool:
        try:
            result = self.__collection.replace_one(criteria, dict(record), upsert=upsert)
        except PyMongoError as error:
            self.__log("update", error)
            return False
        return result.matched_count > 0 or result.upserted_id is not None

    def delete(self, criteria: dict) -> int:
        try:
            return self.__collection.delete_many(criteria).deleted_count
        except PyMongoError as error:
            self.__log("delete", error)
            return 0

    def __log(self, action: str, error: Exception) -> None:
        logger.error("MongoDB %s failed on '%s': %s", action, self.__collection.name, error)