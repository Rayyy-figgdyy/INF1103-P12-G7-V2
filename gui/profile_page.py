"""
ProfilePage: view the profile, change the name or COE date, or delete the profile
and everything saved for its plate.
"""
from __future__ import annotations

import datetime

from gui.gui_page import GuiPage
from models.user_profile import UserProfile


class ProfilePage(GuiPage):
    """INHERITANCE: a GuiPage. Edits go through UserProfile's checked setters."""

    @property
    def title(self) -> str:
        return "My profile"

    def render(self, user: UserProfile | None) -> None:
        self._ui.subheader("My profile")
        self._ui.dataframe([
            {"Detail": "Name", "Value": user.name},
            {"Detail": "Licence plate", "Value": user.license_plate},
            {"Detail": "Car", "Value": f"{user.car_model} ({user.car_condition})"},
            {"Detail": "COE expiry date", "Value": user.coe_expiry_date},
        ], hide_index=True)
        self.__update(user)
        self.__delete(user)

    def __update(self, user: UserProfile) -> None:
        self._ui.subheader("Update my profile")
        earliest, latest = self._services.rules.coe_date_range(
            self._model_year(user), datetime.date.today())
        current_coe = self._parse_date(user.coe_expiry_date) or datetime.date.today()
        current_coe = min(max(current_coe, earliest or current_coe), latest)
        name = self._ui.text_input("Name", value=user.name, key="profile_name")
        coe = self._ui.date_input("COE expiry date", value=current_coe, min_value=earliest,
                                  max_value=latest, format="DD-MM-YYYY", key="profile_coe")
        if not self._ui.button("Save changes", key="profile_save"):
            return
        updated = user.copy()
        try:
            updated.name = name                       # the setters check the new values
            updated.coe_expiry_date = self._text_date(coe)
        except ValueError as error:
            self._ui.error(str(error))
            return
        if not self._services.data.users.save(updated):
            self._ui.error("Could not save your changes. Please try again.")
            return
        self._ui.session_state[self.USER_KEY] = updated
        self._finish("Profile updated.")

    def __delete(self, user: UserProfile) -> None:
        self._ui.subheader("Delete my profile")
        data = self._services.data
        plate = user.license_plate
        sure = self._ui.checkbox(f"Permanently delete {plate} and all its saved history, "
                                 "checks and fuel records", key="profile_delete_sure")
        if not self._ui.button("Delete profile", key="profile_delete", disabled=not sure):
            return
        if not data.users.delete(plate):
            self._ui.error("Could not delete the profile. Please try again.")
            return
        # Remove everything linked to the deleted plate, as the terminal app does.
        data.history.delete_for_plate(plate)
        data.checks.delete_for_plate(plate)
        data.fuel.delete_for_plate(plate)
        data.fuel_assessments.delete_for_plate(plate)
        data.fuel_reviews.delete_for_plate(plate)
        self._ui.session_state.pop(self.USER_KEY, None)
        self._finish("Profile and all its saved data deleted. You have been logged out.")