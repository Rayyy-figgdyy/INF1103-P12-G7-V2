"""
User profiles CRUD (data/users.json), returned as UserProfile objects.
"""
from __future__ import annotations

from models.user_profile import UserProfile
from storage.repository import Repository


class UserRepository:
    """User profiles as UserProfile objects. AGGREGATION: the Repository is created
    outside and passed in, so this class works with any Repository implementation."""

    def __init__(self, repository: Repository):
        self.__repository = repository

    def load_users(self) -> list[UserProfile]:
        """Return every user profile ([] if none yet). Damaged (non-dict) entries are
        skipped."""
        return [UserProfile.from_dict(raw) for raw in self.__repository.find({})]

    def find_by_plate(self, license_plate: str) -> UserProfile | None:
        """Return the profile with this license plate, or None."""
        found = self.__repository.find({"license_plate": license_plate})
        return UserProfile.from_dict(found[0]) if found else None

    def save(self, profile: UserProfile) -> bool:
        """Create a profile, or replace the existing one with the same plate.
        Returns True if it was saved. The other saved profiles are not touched."""
        return self.__repository.replace({"license_plate": profile.license_plate},
                                         profile.to_dict(), upsert=True)

    def delete(self, license_plate: str) -> bool:
        """Delete the profile with this plate (its history and checks are removed
        separately). Returns False if no such profile exists or saving failed."""
        return self.__repository.delete({"license_plate": license_plate}) > 0