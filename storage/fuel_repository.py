# Save fuel records using the same JSON Repository as Part 1.
from __future__ import annotations

import logging

from models.fuel_entry import FuelEntry
from storage.repository import Repository

logger = logging.getLogger("data_manager")


# Handles storage. Calculation rules do not belong in this class.
class FuelRepository:

    def __init__(self, repository: Repository):
        self.__repository = repository   # Aggregation: DataManager owns the store.

    # Return readable entries, ignoring damaged individual records.
    def load_all(self) -> list[FuelEntry]:
        entries = []
        for saved in self.__repository.load_all():
            try:
                entries.append(FuelEntry.from_dict(saved))
            except (TypeError, ValueError) as error:
                logger.warning("Skipping invalid fuel entry: %s", error)
        return entries

    # Get a vehicle's entries in odometer order (only that vehicle's records are read).
    def for_plate(self, license_plate: str) -> list[FuelEntry]:
        entries = []
        for saved in self.__repository.find({"license_plate": license_plate.strip().upper()}):
            try:
                entries.append(FuelEntry.from_dict(saved))
            except (TypeError, ValueError) as error:
                logger.warning("Skipping invalid fuel entry: %s", error)
        return sorted(entries, key=lambda entry: entry.odometer_km)

    # Give a record a unique number and save it.
    def add(self, entry: FuelEntry) -> FuelEntry | None:
        ids = [record.get("entry_id") for record in self.__repository.find({})]
        highest = max((i for i in ids if isinstance(i, int) and not isinstance(i, bool)), default=0)
        new_record = entry.to_dict()
        new_record["entry_id"] = highest + 1
        if not self.__repository.insert(new_record):
            return None
        return FuelEntry.from_dict(new_record)

    # Replace one entry; keep its ID and its other fields.
    def update(self, entry: FuelEntry) -> bool:
        return self.__repository.replace(
            {"entry_id": entry.entry_id, "license_plate": entry.license_plate}, entry.to_dict())

    # Delete an entry; restart measurement at the next one if needed.
    def delete(self, license_plate: str, entry_id: int) -> bool:
        plate = license_plate.strip().upper()
        matching = sorted(self.__repository.find({"license_plate": plate}),
                          key=lambda r: r.get("odometer_km", -1))
        positions = [i for i, item in enumerate(matching)
                     if item.get("entry_id") == entry_id]
        if not positions:
            return False
        pos = positions[0]
        # The next refuel begins a new segment: its litres alone cannot tell
        # us how much fuel was used since the record before the deleted one.
        # It is marked first, so a failed delete can never bridge a missing refuel.
        if pos + 1 < len(matching):
            following = {**matching[pos + 1], "segment_start": True}
            if not self.__repository.replace(
                    {"entry_id": following.get("entry_id"), "license_plate": plate}, following):
                return False
        return self.__repository.delete({"entry_id": entry_id, "license_plate": plate}) > 0

    # Remove all fuel history when its vehicle profile is deleted.
    def delete_for_plate(self, license_plate: str) -> int:
        return self.__repository.delete({"license_plate": license_plate.strip().upper()})