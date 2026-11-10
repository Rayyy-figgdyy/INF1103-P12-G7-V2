"""
<<interface>> Repository: anything that must be able to load and save a list
of records. Implemented with an ABC, as in the Week 9 lecture.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Repository(ABC):
    """INTERFACE (abstract base class): a store of records (a list of dicts).
    The classes below only rely on these two methods, so any subclass -- a JSON file,
    or an in-memory list in the tests -- can be swapped in (Liskov substitution)."""

    @abstractmethod
    def load_all(self) -> list[dict]:
        """Return every saved record ([] if none)."""

    @abstractmethod
    def save_all(self, items: list[dict]) -> bool:
        """Replace all saved records with items. Returns True if it worked."""
