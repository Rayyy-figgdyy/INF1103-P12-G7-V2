# Keep whole-period review decisions separately from the original measurements.
from __future__ import annotations

import datetime
import logging

from storage.repository import Repository

logger = logging.getLogger("data_manager")


class FuelReviewRepository:
    DECISIONS = ("ordinary_variation", "confirmed_fault", "changed_conditions")

    def __init__(self, repository: Repository):
        self.__repository = repository

    # Reject damaged review rows rather than changing their meaning.
    @classmethod
    def __valid(cls, item) -> bool:
        if not isinstance(item, dict) or item.get("decision") not in cls.DECISIONS:
            return False
        if not isinstance(item.get("license_plate"), str) or not item["license_plate"].strip():
            return False
        for field in ("first_entry_id", "through_entry_id"):
            value = item.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                return False
        key = item.get("history_key")
        return isinstance(key, str) and len(key) == 64 and all(
            letter in "0123456789abcdef" for letter in key)

    # Load one vehicle's decisions in the order they were saved.
    def for_plate(self, license_plate: str) -> list[dict]:
        plate = license_plate.strip().upper()
        matching = []
        for item in self.__repository.load_all():
            if self.__valid(item):
                if item["license_plate"] == plate:
                    matching.append(dict(item))
            else:
                logger.warning("Ignoring a damaged fuel review row; "
                               "its measurements remain unchanged.")
        return matching

    # The JSON store refuses to overwrite an unreadable existing file.
    def save(self, review: dict) -> bool:
        if not self.__valid(review):
            raise ValueError("The fuel review is incomplete or invalid.")
        item = dict(review)
        item["license_plate"] = item["license_plate"].strip().upper()
        item["reviewed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return self.__repository.insert(item)

    # Remove only the deleted profile's fuel review history.
    def delete_for_plate(self, license_plate: str) -> int:
        return self.__repository.delete({"license_plate": license_plate.strip().upper()})