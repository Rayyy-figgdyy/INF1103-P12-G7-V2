"""
Saved AI urgency checks (data/prompt_records.json). Also used to spot a
repeated check so the AI isn't asked again (C4).
"""
from __future__ import annotations

from storage.repository import Repository


class CheckRepository:
    """Saved AI checks (records stay plain dicts). AGGREGATION: uses a Repository
    passed in from outside."""

    # Reuse an AI answer only when every input used for that assessment still matches.
    # Eligible Brake Pad replacement history is included so a changed pattern gets a
    # fresh score.
    REPEAT_FIELDS = (
        "license_plate",
        "car_model",
        "car_condition",
        "coe_expiry_date",
        "part_name",
        "last_service_date",
        "last_service_mileage",
        "last_service_action",
        "current_odometer",
        "check_date",
        "interval_km",
        "interval_months",
        "action",
        "interval_stage",
        "brake_pad_history",
        "history_context",
    )

    def __init__(self, repository: Repository):
        self.__repository = repository

    def load(self) -> list[dict]:
        """Return every saved AI check, oldest first ([] if none yet)."""
        return self.__repository.load_all()

    def save(self, record: dict) -> bool:
        """Append one finished check (reads all, adds one, rewrites all).
        Returns True if it was saved."""
        records = self.load()
        records.append(record)
        return self.__repository.save_all(records)

    def query(self, filter_fn) -> list[dict]:
        """Return the saved checks for which filter_fn(check) is True, in saved order.
        Example: query(lambda r: r["part_name"] == "Coolant")"""
        matching = []
        for record in self.load():
            if filter_fn(record):
                matching.append(record)
        return matching

    def for_plate(self, license_plate: str) -> list[dict]:
        """Return the saved checks for one car, in saved order."""
        return self.query(lambda record: isinstance(record, dict)
                          and record.get("license_plate") == license_plate)

    @classmethod
    def same_inputs(cls, record_a: dict, record_b: dict) -> bool:
        """Return True if the two checks match on every field in REPEAT_FIELDS."""
        for field in cls.REPEAT_FIELDS:
            if record_a.get(field) != record_b.get(field):
                return False
        return True

    def find_repeat(self, record: dict) -> dict | None:
        """Return the most recent saved check with the same inputs as record, or None."""
        matches = self.query(lambda saved: self.same_inputs(saved, record))
        if matches:
            return matches[-1]              # checks are appended, so the last match is newest
        return None

    def delete_for_plate(self, license_plate: str) -> int:
        """Delete every saved AI check for one car. Returns how many were deleted.
        AccountController calls this right after deleting the user, so a deleted
        profile leaves no checks."""
        records = self.load()
        remaining = []
        for record in records:
            if not isinstance(record, dict) or record.get("license_plate") != license_plate:
                remaining.append(record)
        removed_count = len(records) - len(remaining)
        if removed_count > 0 and not self.__repository.save_all(remaining):
            return 0                        # the write failed, so nothing was really deleted
        return removed_count

    @staticmethod
    def last_odometer(records: list[dict], license_plate: str) -> int | None:
        """Return the highest odometer reading saved for this car, or None if there is
        none. Works on AI checks (current_odometer) and service entries
        (service_odometer); readings from every part count, since the odometer belongs
        to the whole car."""
        readings = []
        for record in records:
            if not isinstance(record, dict) or record.get("license_plate") != license_plate:
                continue
            for field in ("current_odometer", "service_odometer"):
                odometer = record.get(field)
                # Skip readings that aren't whole numbers (e.g. hand-edited as "45000").
                if isinstance(odometer, int) and not isinstance(odometer, bool):
                    readings.append(odometer)
        if readings:
            return max(readings)
        return None
