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
        return self.__repository.find({"license_plate": license_plate.strip().upper()})

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
        return self.__repository.insert({
            "license_plate": license_plate.strip().upper(),
            "data_key": data_key,
            "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "result": dict(result),
        })

    # Remove reports when the matching profile is deleted.
    def delete_for_plate(self, license_plate: str) -> int:
        return self.__repository.delete({"license_plate": license_plate.strip().upper()})