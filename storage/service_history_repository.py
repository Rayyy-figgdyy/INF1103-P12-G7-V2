"""
Maintenance history CRUD (data/maintenance_history.json).
One entry per service, e.g.
  {"service_id": 3, "license_plate": "SBA1234A", "part_name": "Engine Oil",
   "service_date": "20-03-2026", "service_odometer": 58000, "notes": "Ah Seng Motors"}
"""
from __future__ import annotations

from storage.repository import Repository


class ServiceHistoryRepository:
    """The service log (entries stay plain dicts). AGGREGATION: uses a Repository
    passed in from outside."""

    def __init__(self, repository: Repository):
        self.__repository = repository

    def load_all(self) -> list[dict]:
        """Return every service entry for every car, in saved order ([] if none yet)."""
        return self.__repository.find({})

    def for_plate(self, license_plate: str) -> list[dict]:
        """Return the service entries for one car, in saved order."""
        return self.__repository.find({"license_plate": license_plate})

    def for_part(self, license_plate: str, part_name: str) -> list[dict]:
        """Return all matching history entries in saved order, keeping their raw fields."""
        return self.__repository.find({"license_plate": license_plate, "part_name": part_name})

    @staticmethod
    def next_service_id(entries: list[dict]) -> int:
        """Return one more than the highest service_id in use (1 for an empty list)."""
        highest = 0
        for entry in entries:
            service_id = entry.get("service_id")
            if isinstance(service_id, int) and service_id > highest:
                highest = service_id
        return highest + 1

    def add(self, entry: dict) -> dict | None:
        """CREATE: give the entry a new service_id and save it.
        Returns the saved entry (with its id), or None if saving failed."""
        new_entry = dict(entry)
        new_entry["service_id"] = self.next_service_id(self.load_all())
        if not self.__repository.insert(new_entry):
            return None
        return new_entry

    def update(self, updated: dict) -> bool:
        """UPDATE: replace the saved entry that has the same service_id.
        Returns False if no entry has that id or saving failed."""
        return self.__repository.replace({"service_id": updated.get("service_id")}, updated)

    def delete(self, service_id: int) -> bool:
        """DELETE: remove the entry with this service_id.
        Returns False if no entry has that id or saving failed."""
        return self.__repository.delete({"service_id": service_id}) > 0

    def delete_for_plate(self, license_plate: str) -> int:
        """Delete every service entry for one car. Returns how many were deleted.
        AccountController calls this when a profile is deleted."""
        return self.__repository.delete({"license_plate": license_plate})