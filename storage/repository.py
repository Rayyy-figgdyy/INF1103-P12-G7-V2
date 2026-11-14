"""
<<interface>> Repository: anything that must be able to store records (dicts) and
create, read, update and delete them. Implemented with an ABC, as in the Week 9 lecture.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Repository(ABC):
    """INTERFACE (abstract base class): a store of records (a list of dicts).
    The repositories only rely on these methods, so any implementation -- a JSON file,
    a MongoDB collection, or an in-memory list in the tests -- can be swapped in
    (Liskov substitution). A `criteria` dict matches records whose fields are equal,
    e.g. {"license_plate": "SBA1234A"}."""

    @abstractmethod
    def load_all(self) -> list[dict]:
        """Return every saved record ([] if none)."""

    @abstractmethod
    def save_all(self, items: list[dict]) -> bool:
        """Replace all saved records with items. Returns True if it worked."""

    @abstractmethod
    def find(self, criteria: dict) -> list[dict]:
        """READ: the records matching criteria, in saved order ([] if none)."""

    @abstractmethod
    def insert(self, record: dict) -> bool:
        """CREATE: add one record. Returns True if it was saved."""

    @abstractmethod
    def replace(self, criteria: dict, record: dict, upsert: bool = False) -> bool:
        """UPDATE: replace the first record matching criteria. With upsert=True, add
        the record when nothing matches. Returns True if it was saved."""

    @abstractmethod
    def delete(self, criteria: dict) -> int:
        """DELETE: remove every record matching criteria. Returns how many were removed
        (0 if none matched or saving failed)."""