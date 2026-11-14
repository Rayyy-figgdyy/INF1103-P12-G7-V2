"""
MongoConnection: the one place that connects to MongoDB (e.g. a free MongoDB Atlas
cluster). A failed connection is logged and gives None, so the app can carry on with
the JSON files instead of crashing.
"""
from __future__ import annotations

import logging

import certifi
from pymongo import MongoClient
from pymongo.errors import PyMongoError

# Logged under the Data Manager's name, so its messages read "data_manager: ...".
logger = logging.getLogger("data_manager")


class MongoConnection:
    """ENCAPSULATION: the client and database are private; repositories only get a
    collection through collection(). connect() is a factory method: it returns a
    working connection, or None."""

    TIMEOUT_MS = 5000               # give up after 5 seconds instead of hanging

    def __init__(self, client, database_name: str):
        self.__client = client
        self.__database_name = database_name
        self.__database = client[database_name]

    @classmethod
    def connect(cls, uri: str, database_name: str) -> MongoConnection | None:
        """Connect and check that the server answers (ping). Returns None if it can't
        be reached: wrong address, wrong password, no internet or IP not allowed."""
        options = {"serverSelectionTimeoutMS": cls.TIMEOUT_MS}
        if uri.startswith("mongodb+srv://"):
            options["tlsCAFile"] = certifi.where()    # Atlas needs TLS certificates
        try:
            client = MongoClient(uri, **options)
            client.admin.command("ping")
        except PyMongoError as error:
            # The URI holds the password, so only the error is logged, never the URI.
            logger.warning("Could not connect to MongoDB: %s", error)
            return None
        return cls(client, database_name)

    @property
    def database_name(self) -> str:
        return self.__database_name

    def collection(self, name: str):
        """The MongoDB collection with this name (created when first written to)."""
        return self.__database[name]