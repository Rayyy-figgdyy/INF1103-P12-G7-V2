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
        return self.__repository.load_all()

    def for_plate(self, license_plate: str) -> list[dict]:
        """Return the service entries for one car, in saved order."""
        entries = []
        for entry in self.load_all():
            if isinstance(entry, dict) and entry.get("license_plate") == license_plate:
                entries.append(entry)
        return entries

    def for_part(self, license_plate: str, part_name: str) -> list[dict]:
        """Return all matching history entries in saved order, keeping their raw fields."""
        entries = []
        for entry in self.for_plate(license_plate):
            if entry.get("part_name") == part_name:
                entries.append(entry)
        return entries

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
        entries = self.load_all()
        new_entry = dict(entry)
        new_entry["service_id"] = self.next_service_id(entries)
        entries.append(new_entry)
        if not self.__repository.save_all(entries):
            return None
        return new_entry

    def update(self, updated: dict) -> bool:
        """UPDATE: replace the saved entry that has the same service_id.
        Returns False if no entry has that id or saving failed."""
        entries = self.load_all()
        for position in range(len(entries)):
            if entries[position].get("service_id") == updated.get("service_id"):
                entries[position] = updated
                return self.__repository.save_all(entries)
        return False

    def delete(self, service_id: int) -> bool:
        """DELETE: remove the entry with this service_id.
        Returns False if no entry has that id or saving failed."""
        entries = self.load_all()
        remaining = []
        for entry in entries:
            if entry.get("service_id") != service_id:
                remaining.append(entry)
        if len(remaining) == len(entries):
            return False                    # id not found
        return self.__repository.save_all(remaining)

    def delete_for_plate(self, license_plate: str) -> int:
        """Delete every service entry for one car. Returns how many were deleted.
        AccountController calls this when a profile is deleted."""
        entries = self.load_all()
        remaining = []
        for entry in entries:
            if entry.get("license_plate") != license_plate:
                remaining.append(entry)
        removed_count = len(entries) - len(remaining)
        if removed_count > 0 and not self.__repository.save_all(remaining):
            return 0                        # the write failed, so nothing was really deleted
        return removed_count
