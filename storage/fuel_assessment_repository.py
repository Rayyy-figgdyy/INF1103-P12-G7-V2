# Save completed AI fuel reports in JSON, like Part 1's AI check records.
from __future__ import annotations

import datetime

from storage.repository import Repository


# Store valid AI results and reuse the result for unchanged readings.
class FuelAssessmentRepository:

    def __init__(self, repository: Repository):
        self.__repository = repository

    # Find reports saved for one vehicle.
    def for_plate(self, license_plate: str) -> list[dict]:
        plate = license_plate.strip().upper()
        return [entry for entry in self.__repository.load_all()
                if isinstance(entry, dict) and entry.get("license_plate") == plate]

    # Do not call AI again when the same report has already been saved.
    def find_repeat(self, license_plate: str, data_key: str) -> dict | None:
        for entry in reversed(self.for_plate(license_plate)):
            result = entry.get("result")
            if (entry.get("data_key") == data_key and isinstance(result, dict)
                    and result.get("ai_status") == "ok"):
                return dict(result)
        return None

    # Save a successful assessment; failed AI calls are never faked or saved.
    def save(self, license_plate: str, data_key: str, result: dict) -> bool:
        if result.get("ai_status") != "ok":
            return False
        records = self.__repository.load_all()
        records.append({
            "license_plate": license_plate.strip().upper(),
            "data_key": data_key,
            "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "result": dict(result),
        })
        return self.__repository.save_all(records)

    # Remove reports when the matching profile is deleted.
    def delete_for_plate(self, license_plate: str) -> int:
        records = self.__repository.load_all()
        plate = license_plate.strip().upper()
        keep = [item for item in records if not (
            isinstance(item, dict) and item.get("license_plate") == plate)]
        removed = len(records) - len(keep)
        if removed and not self.__repository.save_all(keep):
            return 0
        return removed
