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
        users = []
        for raw in self.__repository.load_all():
            if isinstance(raw, dict):
                users.append(UserProfile.from_dict(raw))
        return users

    def find_by_plate(self, license_plate: str) -> UserProfile | None:
        """Return the profile with this license plate, or None."""
        for user in self.load_users():
            if user.license_plate == license_plate:
                return user
        return None

    def save(self, profile: UserProfile) -> bool:
        """Create a profile, or replace the existing one with the same plate.
        Returns True if it was saved. The other saved profiles are kept exactly as
        they are in the file."""
        users_to_keep = []
        for existing in self.__repository.load_all():
            if not isinstance(existing, dict) or \
                    existing.get("license_plate") != profile.license_plate:
                users_to_keep.append(existing)
        users_to_keep.append(profile.to_dict())  # an old copy with this plate was left out
        return self.__repository.save_all(users_to_keep)

    def delete(self, license_plate: str) -> bool:
        """Delete the profile with this plate (its history and checks are removed
        separately). Returns False if no such profile exists or saving failed."""
        users = self.__repository.load_all()
        remaining = []
        for user in users:
            if not isinstance(user, dict) or user.get("license_plate") != license_plate:
                remaining.append(user)
        if len(remaining) == len(users):
            return False                    # plate not found
        return self.__repository.save_all(remaining)
