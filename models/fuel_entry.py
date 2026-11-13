# A single full-tank refuel. The calculations belong in the logic layer.
from __future__ import annotations

from datetime import datetime, date
from math import isfinite


# Store the three things the driver enters, plus a saved record ID.
class FuelEntry:

    DATE_FORMAT = "%d-%m-%Y"
    MAX_ODOMETER_KM = 2_000_000

    def __init__(self, license_plate: str, refuel_date: str, odometer_km: int,
                 litres: float, entry_id: int | None = None,
                 segment_start: bool = False):
        if not isinstance(license_plate, str) or not license_plate.strip():
            raise ValueError("A licence plate is required.")
        if not isinstance(refuel_date, str):
            raise ValueError("Use DD-MM-YYYY for the date.")
        try:
            recorded_date = datetime.strptime(refuel_date, self.DATE_FORMAT).date()
        except ValueError as error:
            raise ValueError("Use a real date in DD-MM-YYYY format.") from error
        if recorded_date > date.today():
            raise ValueError("A refuel cannot be dated in the future.")
        if (isinstance(odometer_km, bool) or not isinstance(odometer_km, int)
                or not 0 <= odometer_km <= self.MAX_ODOMETER_KM):
            raise ValueError("Odometer must be a whole number from 0 to 2,000,000 km.")
        if (isinstance(litres, bool) or not isinstance(litres, (int, float))
                or not isfinite(litres) or not 0 < litres <= 200):
            raise ValueError("Litres must be a number greater than 0 and at most 200.")
        if (entry_id is not None and (isinstance(entry_id, bool)
                or not isinstance(entry_id, int) or entry_id < 1)):
            raise ValueError("Record ID must be a positive number.")
        if not isinstance(segment_start, bool):
            raise ValueError("Invalid tracking segment flag.")

        self.__license_plate = license_plate.strip().upper()
        self.__refuel_date = refuel_date
        self.__odometer_km = odometer_km
        self.__litres = float(litres)
        self.__entry_id = entry_id
        # A segment starts after a record was deleted. Do not bridge missing fuel.
        self.__segment_start = segment_start

    @property
    def license_plate(self) -> str:
        return self.__license_plate

    @property
    def refuel_date(self) -> str:
        return self.__refuel_date

    @property
    def odometer_km(self) -> int:
        return self.__odometer_km

    @property
    def litres(self) -> float:
        return self.__litres

    @property
    def entry_id(self) -> int | None:
        return self.__entry_id

    @property
    def segment_start(self) -> bool:
        return self.__segment_start

    # Convert the object into simple values JSON can save.
    def to_dict(self) -> dict:
        return {"entry_id": self.__entry_id,
                "license_plate": self.__license_plate,
                "refuel_date": self.__refuel_date,
                "odometer_km": self.__odometer_km,
                "litres": self.__litres,
                "segment_start": self.__segment_start}

    # Check old records when reading them, just like new inputs.
    @classmethod
    def from_dict(cls, record: dict) -> FuelEntry:
        if not isinstance(record, dict):
            raise ValueError("Saved fuel record must be a dictionary.")
        return cls(record.get("license_plate"), record.get("refuel_date"),
                   record.get("odometer_km"), record.get("litres"),
                   record.get("entry_id"), record.get("segment_start", False))
