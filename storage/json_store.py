"""
The only class that opens a data file. Every file error is handled here,
so a missing or corrupt file never crashes the app.
"""
from __future__ import annotations

import json
import logging
import os

# Logged under the Data Manager's name, so its messages read "data_manager: ...".
logger = logging.getLogger("data_manager")


class JsonStore:
    """One JSON file on disk. Encapsulation: the path is private and every file
    access (with its error handling) is hidden behind read / read_list / write_list."""

    def __init__(self, path: str):
        self.__path = path

    @property
    def path(self) -> str:
        return self.__path

    def read(self):
        """Read the file and return its contents.
        Returns None if the file is missing, empty or damaged (problems are logged)."""
        try:
            with open(self.__path, "r", encoding="utf-8") as file:
                content = file.read().strip()
            data = json.loads(content) if content else None
        except FileNotFoundError:
            return None                     # no file yet: normal on first run
        except (OSError, json.JSONDecodeError) as error:
            # OSError (e.g. PermissionError) = the file can't be read;
            # JSONDecodeError = the text isn't valid JSON.
            # Log it and carry on as if there were no data, instead of crashing.
            logger.error("Could not read %s (missing permission or corrupt JSON): %s",
                         self.__path, error)
            return None
        else:
            return data                     # the file was read and parsed

    def read_list(self) -> list[dict]:
        """Read a file that should hold a list (checks, history or users).
        Returns that list, or [] if the file is missing, damaged or not a list."""
        data = self.read()
        if isinstance(data, list):
            return data
        if data is not None:                # None was already logged by read()
            logger.error("%s does not contain a list -- ignoring its contents.", self.__path)
        return []

    def write_list(self, items: list[dict]) -> bool:
        """Overwrite the file with the whole list, creating its folder if needed.
        Returns True on success, False if writing failed (the error is logged)."""
        try:
            os.makedirs(os.path.dirname(self.__path), exist_ok=True)
            with open(self.__path, "w", encoding="utf-8") as file:
                json.dump(items, file, indent=2)
            return True
        except OSError as error:
            logger.error("Could not write %s: %s", self.__path, error)
            return False
