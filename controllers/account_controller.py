"""
Menu options for accounts: login, register, view, update and delete a profile.
"""
from __future__ import annotations

import datetime

from data_manager import DataManager
from io_manager import IOManager
from logic.history_rules import HistoryRules
from models.user_profile import UserProfile


class AccountController:
    """Login and profile CRUD. Returns UserProfile objects (or None when logged out).
    AGGREGATION: the managers are passed in and shared with other controllers.
    ASSOCIATION: each method is handed the logged-in UserProfile, uses it and gives
    it back, without keeping it."""

    def __init__(self, io: IOManager, data: DataManager, rules: HistoryRules):
        self.__io = io
        self.__data = data
        self.__rules = rules

    def __coe_limits(self, car_model: str) -> tuple:
        """The allowed COE expiry range for this car, as of today."""
        return self.__rules.coe_date_range(self.__data.cars.get_model_year(car_model),
                                          datetime.date.today())

    def __with_car(self, profile: UserProfile) -> UserProfile:
        """Give the profile its Car from the catalogue (aggregation)."""
        profile.attach_car(self.__data.cars.find(profile.car_model))
        return profile

    def login(self) -> UserProfile | None:
        """Find the profile for a licence plate, or None if it is not registered."""
        plate = self.__io.prompt_login()
        user = self.__data.users.find_by_plate(plate)
        if user is None:
            self.__io.display_message(f"No profile for {plate}. Choose 'Register new profile' first.")
            return None
        self.__io.display_message(f"\nWelcome back, {user.name}!")
        return self.__with_car(user)

    def register(self) -> UserProfile | None:
        """Create a new profile and log in, or None if registration can't be completed."""
        car_models = self.__data.cars.list_models()
        if not car_models:
            self.__io.display_message("The car list (data/cars.json) is missing, so you can't register yet.")
            return None

        # The plate is the account ID, so plates already taken are refused.
        taken_plates = {user.license_plate for user in self.__data.users.load_users()}
        identity = self.__io.prompt_identity(taken_plates)
        car_model = self.__io.prompt_car_choice(car_models)
        car = self.__data.cars.find(car_model)
        earliest_coe, latest_coe = self.__coe_limits(car_model)

        # Brand New / Used comes from the car list, not from the user.
        profile = UserProfile(identity["name"], identity["license_plate"], car_model,
                              car.condition,
                              self.__io.prompt_coe_expiry(earliest_coe, latest_coe))
        if not self.__data.users.save(profile):
            self.__io.display_message("Could not save your profile. Please try again.")
            return None
        self.__io.display_message("\nProfile created -- you are now logged in.")
        self.__io.display_user(profile)
        return self.__with_car(profile)

    def show_profile(self, user: UserProfile) -> UserProfile:
        self.__io.display_user(user)
        return user

    def update_profile(self, user: UserProfile) -> UserProfile:
        """Change the name or COE date; keeps the old profile if saving fails."""
        earliest_coe, latest_coe = self.__coe_limits(user.car_model)
        updated = self.__io.prompt_updated_profile(user, earliest_coe, latest_coe)
        if not self.__data.users.save(updated):
            self.__io.display_message("Could not save your changes. Please try again.")
            return user
        self.__io.display_message("\nProfile updated.")
        self.__io.display_user(updated)
        return updated

    def delete_profile(self, user: UserProfile) -> UserProfile | None:
        """Delete the profile and everything linked to its plate, after confirmation.
        Returns None when deleted (logged out), else the same user."""
        plate = user.license_plate
        service_count = len(self.__data.history.for_plate(plate))
        check_count = len(self.__data.checks.for_plate(plate))
        question = (f"Permanently delete {plate}, its {service_count} service(s) and "
                    f"{check_count} urgency check(s)?")
        if not self.__io.confirm_action(question):
            self.__io.display_message("Delete cancelled.")
            return user
        if not self.__data.users.delete(plate):
            self.__io.display_message("Could not delete the profile. Please try again.")
            return user
        # Remove the history and assessments linked to the deleted plate.
        self.__data.history.delete_for_plate(plate)
        self.__data.checks.delete_for_plate(plate)
        self.__io.display_message("Profile, history and checks deleted. You have been logged out.")
        return None

    def logout(self, user: UserProfile) -> None:
        self.__io.display_message(f"Logged out {user.name}.")
        return None
