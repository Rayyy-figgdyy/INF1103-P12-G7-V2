"""
AccountPage: log in or register (shown before anyone is logged in). The same checks
as the terminal app: plate shape, plate not taken, and the COE date range.
"""
from __future__ import annotations

import datetime

from gui.gui_page import GuiPage
from io_manager import IOManager
from models.user_profile import UserProfile


class AccountPage(GuiPage):
    """INHERITANCE: a GuiPage. A successful login stores the user in the session."""

    @property
    def title(self) -> str:
        return "Log in or register"

    def render(self, user: UserProfile | None) -> None:
        login_tab, register_tab = self._ui.tabs(["Log in", "Register"])
        with login_tab:
            self.__login()
        with register_tab:
            self.__register()

    def __start_session(self, profile: UserProfile, message: str) -> None:
        """Give the profile its Car (aggregation), remember it and redraw the page."""
        profile.attach_car(self._services.data.cars.find(profile.car_model))
        self._ui.session_state[self.USER_KEY] = profile
        self._finish(message)

    def __login(self) -> None:
        typed = self._ui.text_input("Licence plate", key="login_plate",
                                    placeholder="e.g. SBA1234A")
        if not self._ui.button("Log in", key="login_button"):
            return
        plate = IOManager.normalise_plate(typed)
        profile = self._services.data.users.find_by_plate(plate)
        if profile is None:
            self._ui.error(f"No profile for {plate or 'that plate'}. Register first.")
            return
        self.__start_session(profile, f"Welcome back, {profile.name}!")

    def __register(self) -> None:
        data = self._services.data
        models = data.cars.list_models()
        if not models:
            self._ui.error("The car list (data/cars.json) is missing, so you can't register yet.")
            return
        name = self._ui.text_input("Name", key="register_name")
        typed_plate = self._ui.text_input("Licence plate", key="register_plate",
                                          placeholder="e.g. SBA1234A")
        car_model = self._ui.selectbox("Car", models, key="register_car")
        earliest, latest = self._services.rules.coe_date_range(
            data.cars.get_model_year(car_model), datetime.date.today())
        coe = self._ui.date_input("COE expiry date", value=datetime.date.today(),
                                  min_value=earliest, max_value=latest,
                                  format="DD-MM-YYYY", key=f"register_coe_{car_model}")
        if not self._ui.button("Register", key="register_button"):
            return

        plate = IOManager.normalise_plate(typed_plate)
        taken = {profile.license_plate for profile in data.users.load_users()}
        problem = None
        if not name.strip():
            problem = "Name cannot be empty."
        elif not IOManager.LICENSE_PLATE_PATTERN.match(plate):
            problem = "Licence plate must look like SBA1234A (letters, digits, then a letter)."
        elif plate in taken:
            problem = f"{plate} is already registered. Log in instead."
        elif IOManager.coe_problem(coe, earliest, latest) is not None:
            problem = "COE expiry date " + IOManager.coe_problem(coe, earliest, latest) + "."
        if problem:
            self._ui.error(problem)
            return

        car = data.cars.find(car_model)
        profile = UserProfile(name.strip(), plate, car_model, car.condition, self._text_date(coe))
        if not data.users.save(profile):
            self._ui.error("Could not save your profile. Please try again.")
            return
        self.__start_session(profile, "Profile created. You are now logged in.")