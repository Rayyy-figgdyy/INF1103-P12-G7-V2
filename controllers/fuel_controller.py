# Connect the terminal screens to fuel records, review decisions and AI assessments.
from __future__ import annotations

from data_manager import DataManager
from io_manager import IOManager
from ai_manager import AIManager
from logic_manager import LogicManager
from models.user_profile import UserProfile
from services.fuel_service import FuelService
from logic.history_rules import HistoryRules


class FuelController:

    # The controller connects managers; managers do not import one another.
    def __init__(self, io: IOManager, data: DataManager,
                 ai: AIManager, logic: LogicManager):
        self.__io = io
        self.__ai = ai
        self.__logic = logic
        self.__data = data
        self.__fuel = FuelService(data.fuel, data.fuel_assessments,
                                  maintenance_history=data.history,
                                  maintenance_rules=HistoryRules(), reviews=data.fuel_reviews)

    # All fuel menu options stay in the existing command-line application.
    def run(self, user: UserProfile) -> UserProfile:
        while True:
            choice = self.__io.prompt_fuel_menu()
            if choice == "7":
                return user
            if choice == "1":
                self.__add(user)
            elif choice == "2":
                self.__view(user)
            elif choice == "3":
                self.__edit(user)
            elif choice == "4":
                self.__delete(user)
            elif choice == "5":
                self.__analyse(user)
            elif choice == "6":
                self.__review(user)
            else:
                self.__io.display_message("Choose a number from 1 to 7.")

    # Adding a record asks for only its date, odometer and litres.
    def __add(self, user: UserProfile) -> None:
        self.__io.display_message("\nEvery recorded refuel must fill the tank completely.")
        details = self.__io.prompt_fuel_entry()
        try:
            saved = self.__fuel.add_refuel(user.license_plate, **details)
        except (ValueError, OSError) as error:
            self.__io.display_message(f"Could not add refuel: {error}")
            return
        self.__io.display_message(f"Saved full-tank refuel #{saved.entry_id}.")
        self.__io.display_fuel_dashboard(self.__fuel.get_dashboard(user.license_plate, user.car_model))

    # Viewing saved measurements does not spend another API call.
    def __view(self, user: UserProfile) -> None:
        self.__io.display_fuel_dashboard(self.__fuel.get_dashboard(user.license_plate, user.car_model))

    # Edits revalidate and recalculate; AI runs only when Analyse is selected.
    def __edit(self, user: UserProfile) -> None:
        old = self.__io.prompt_fuel_choice(self.__fuel.get_history(user.license_plate), "edit")
        if old is None:
            return
        details = self.__io.prompt_fuel_entry(old)
        try:
            self.__fuel.update_refuel(user.license_plate, old.entry_id, **details)
        except (ValueError, OSError) as error:
            self.__io.display_message(f"Could not update refuel: {error}")
            return
        self.__io.display_message("Fuel record updated. Results have been recalculated.")
        self.__io.display_fuel_dashboard(self.__fuel.get_dashboard(user.license_plate, user.car_model))

    # Missing refuels break measurement continuity rather than inventing an interval.
    def __delete(self, user: UserProfile) -> None:
        selected = self.__io.prompt_fuel_choice(self.__fuel.get_history(user.license_plate), "delete")
        if selected is None or not self.__io.confirm_action(f"Delete fuel record #{selected.entry_id}?"):
            return
        if self.__fuel.delete_refuel(user.license_plate, selected.entry_id):
            self.__io.display_message("Deleted. Measurement restarts at the next recorded full tank.")
            self.__io.display_fuel_dashboard(self.__fuel.get_dashboard(user.license_plate, user.car_model))
        else:
            self.__io.display_message("Could not delete fuel record.")

    # Show a progress message only when a fresh AI request is about to run.
    def __show_ai_progress(self) -> None:
        self.__io.display_message("\nGenerating a new AI report...")

    # Only this menu action requests AI; validation and saved-report reuse happen first.
    def __analyse(self, user: UserProfile) -> None:
        try:
            result = self.__fuel.analyse_with_ai(user.license_plate, self.__ai,
                                               user.car_model, self.__logic,
                                               before_request=self.__show_ai_progress)
            if result.get("reused"):
                self.__io.display_message("\nReport previously generated. No data has changed; "
                                          "showing saved report.")
            self.__io.display_fuel_ai(result)
        except (ValueError, OSError) as error:
            self.__io.display_message(f"Could not complete the fuel assessment: {error}")

    # One decision applies to the complete open period, not one menu step per refuel.
    def __review(self, user: UserProfile) -> None:
        dashboard = self.__fuel.get_dashboard(user.license_plate, user.car_model)
        if not dashboard["alert_active"]:
            self.__io.display_message("There is no open fuel alert to review.")
            return
        decision = self.__io.prompt_fuel_review(dashboard["alert"])
        if decision is None:
            return
        try:
            self.__fuel.review_alert(user.license_plate, decision)
        except (ValueError, OSError) as error:
            self.__io.display_message(f"Could not save the fuel review: {error}")
            return
        self.__io.display_message("Review saved. All original fuel records are retained.")
        self.__io.display_fuel_dashboard(self.__fuel.get_dashboard(user.license_plate, user.car_model))

    # Profile deletion removes only that vehicle's fuel records, reports and reviews.
    def delete_profile_data(self, license_plate: str) -> None:
        self.__data.fuel.delete_for_plate(license_plate)
        self.__data.fuel_assessments.delete_for_plate(license_plate)
        self.__data.fuel_reviews.delete_for_plate(license_plate)
