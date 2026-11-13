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

    # Get a vehicle's entries in odometer order.
    def for_plate(self, license_plate: str) -> list[FuelEntry]:
        plate = license_plate.strip().upper()
        entries = [entry for entry in self.load_all() if entry.license_plate == plate]
        return sorted(entries, key=lambda entry: entry.odometer_km)

    # Give a record a unique number and save it.
    def add(self, entry: FuelEntry) -> FuelEntry | None:
        records = self.__repository.load_all()
        ids = [r.get("entry_id") for r in records if isinstance(r, dict)]
        highest = max((i for i in ids if isinstance(i, int) and not isinstance(i, bool)), default=0)
        new_record = entry.to_dict()
        new_record["entry_id"] = highest + 1
        records.append(new_record)
        if not self.__repository.save_all(records):
            return None
        return FuelEntry.from_dict(new_record)

    # Replace one entry; keep its ID and its other fields.
    def update(self, entry: FuelEntry) -> bool:
        records = self.__repository.load_all()
        for index, record in enumerate(records):
            if (isinstance(record, dict) and record.get("entry_id") == entry.entry_id
                    and record.get("license_plate") == entry.license_plate):
                records[index] = entry.to_dict()
                return self.__repository.save_all(records)
        return False

    # Delete an entry; restart measurement at the next one if needed.
    def delete(self, license_plate: str, entry_id: int) -> bool:
        records = self.__repository.load_all()
        plate = license_plate.strip().upper()
        matching = sorted((r for r in records if isinstance(r, dict)
                           and r.get("license_plate") == plate),
                          key=lambda r: r.get("odometer_km", -1))
        positions = [i for i, item in enumerate(matching)
                     if item.get("entry_id") == entry_id]
        if not positions:
            return False
        pos = positions[0]
        # The next refuel begins a new segment: its litres alone cannot tell
        # us how much fuel was used since the record before the deleted one.
        if pos + 1 < len(matching):
            matching[pos + 1]["segment_start"] = True
        keep = [r for r in records if not (isinstance(r, dict)
                and r.get("entry_id") == entry_id and r.get("license_plate") == plate)]
        return self.__repository.save_all(keep)

    # Remove all fuel history when its vehicle profile is deleted.
    def delete_for_plate(self, license_plate: str) -> int:
        plate = license_plate.strip().upper()
        records = self.__repository.load_all()
        keep = [r for r in records if not (isinstance(r, dict)
                and r.get("license_plate") == plate)]
        removed = len(records) - len(keep)
        if removed and not self.__repository.save_all(keep):
            return 0
        return removed
