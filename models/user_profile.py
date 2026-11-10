"""
A registered car owner. ENCAPSULATION (Week 9): every attribute is private and is
read through a @property. Only the name and COE date can be changed, through
setters that check the new value first.
"""
from __future__ import annotations

import datetime

from models.car import Car


class UserProfile:
    """A car owner. The licence plate is the account's ID, so it can't change.
    AGGREGATION: the profile is given a Car from the catalogue (attach_car); the Car
    exists on its own and is not deleted with the profile."""

    DATE_FORMAT = "%d-%m-%Y"

    def __init__(self, name: str, license_plate: str, car_model: str,
                 car_condition: str, coe_expiry_date: str):
        # Saved values are stored as they are (a damaged users.json entry may have
        # None in it); the setters below check values the user changes.
        self.__name = name
        self.__license_plate = license_plate
        self.__car_model = car_model
        self.__car_condition = car_condition
        self.__coe_expiry_date = coe_expiry_date
        self.__car = None

    # ---- read-only: these identify the account ----

    @property
    def license_plate(self) -> str:
        return self.__license_plate

    @property
    def car_model(self) -> str:
        return self.__car_model

    @property
    def car_condition(self) -> str:
        return self.__car_condition

    # ---- readable and changeable, with a check ----

    @property
    def name(self) -> str:
        return self.__name

    @name.setter
    def name(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Name cannot be empty.")
        self.__name = value.strip()

    @property
    def coe_expiry_date(self) -> str:
        """The COE expiry date as DD-MM-YYYY text."""
        return self.__coe_expiry_date

    @coe_expiry_date.setter
    def coe_expiry_date(self, value: str) -> None:
        # strptime raises ValueError for text that isn't a real DD-MM-YYYY date.
        datetime.datetime.strptime(value, self.DATE_FORMAT)
        self.__coe_expiry_date = value

    # ---- the Car this owner drives (aggregation) ----

    @property
    def car(self) -> Car | None:
        """The catalogue Car this owner drives (None if it is no longer supported)."""
        return self.__car

    def attach_car(self, car: Car | None) -> None:
        self.__car = car

    # ---- copying and saving ----

    def copy(self) -> UserProfile:
        """A separate copy, so edits can be checked before they are saved."""
        clone = UserProfile(self.__name, self.__license_plate, self.__car_model,
                            self.__car_condition, self.__coe_expiry_date)
        clone.attach_car(self.__car)
        return clone

    def to_dict(self) -> dict:
        """The profile as stored in users.json."""
        return {"name": self.__name, "license_plate": self.__license_plate,
                "car_model": self.__car_model, "car_condition": self.__car_condition,
                "coe_expiry_date": self.__coe_expiry_date}

    @classmethod
    def from_dict(cls, raw: dict) -> UserProfile:
        """Build a profile from users.json; missing fields become None, not a crash."""
        return cls(raw.get("name"), raw.get("license_plate"), raw.get("car_model"),
                   raw.get("car_condition"), raw.get("coe_expiry_date"))
