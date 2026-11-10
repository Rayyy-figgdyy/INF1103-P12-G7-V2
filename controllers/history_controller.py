"""
Menu options 1-4: add, view, edit and delete maintenance history (CRUD).
"""
from __future__ import annotations

import datetime

from data_manager import DataManager
from io_manager import IOManager
from logic.history_rules import HistoryRules
from models.user_profile import UserProfile


class HistoryController:
    """Maintenance history CRUD: add invoices, view, edit and delete services.
    AGGREGATION: the managers are passed in. ASSOCIATION: each method uses the
    UserProfile it is handed, without keeping it."""

    def __init__(self, io: IOManager, data: DataManager, rules: HistoryRules):
        self.__io = io
        self.__data = data
        self.__rules = rules

    # ---------- shared helpers ----------

    def __model_year(self, user: UserProfile) -> int | None:
        """The model year of the user's car (via the associated Car when available)."""
        if user.car is not None:
            return user.car.model_year
        return self.__data.cars.get_model_year(user.car_model)

    def earliest_service_date(self, user: UserProfile) -> datetime.date | None:
        """1 January of the model year: no service can be dated before the car was made."""
        model_year = self.__model_year(user)
        return None if model_year is None else datetime.date(model_year, 1, 1)

    def __service_problem(self, user: UserProfile, entries: list[dict], service_date: str,
                         odometer: int, ignore_id: int | None = None) -> str | None:
        """Business rule 1 (odometer never goes backwards) and the km-per-day limit."""
        problem = self.__rules.check_service_odometer(entries, service_date, odometer, ignore_id)
        if problem is not None:
            return problem
        return self.__rules.check_service_pace(entries, service_date, odometer,
                                              self.__model_year(user), ignore_id)

    # ---------- add ----------

    def __prompt_valid_invoice(self, user: UserProfile, history: list[dict], parts: list[str],
                              part_name: str | None = None) -> dict | None:
        """Ask for an invoice until its date and mileage fit the saved history."""
        while True:
            invoice = self.__io.prompt_service_entry(parts, part_name,
                                                    self.earliest_service_date(user))
            problem = self.__service_problem(user, history, invoice["service_date"],
                                            invoice["service_odometer"])
            if problem is None:
                return invoice
            self.__io.display_message(f"  -> {problem}")
            if not self.__io.confirm_action("Enter this invoice again?"):
                return None

    def __save_invoice_part(self, user: UserProfile, history: list[dict], invoice: dict,
                           part_name: str) -> dict | None:
        """Save one part of an invoice as its own history entry (skipping duplicates)."""
        service_action = invoice["service_actions"][part_name]
        duplicate = self.__rules.find_duplicate_service(
            history, part_name, invoice["service_date"], invoice["service_odometer"],
            service_action=service_action)
        if duplicate is not None:
            self.__io.display_message(
                f"  -> {part_name} on {invoice['service_date']} at "
                f"{invoice['service_odometer']:,} km is already in your history, "
                "so it was not added again.")
            return None

        entry = {
            "license_plate": user.license_plate,
            "part_name": part_name,
            "service_action": service_action,
            "service_date": invoice["service_date"],
            "service_odometer": invoice["service_odometer"],
            "notes": invoice["notes"],
        }
        saved = self.__data.history.add(entry)
        if saved is None:
            self.__io.display_message(f"Could not save the {part_name} service. Please try again.")
        return saved

    def add_services(self, user: UserProfile, part_name: str | None = None) -> list[dict]:
        """Ask for one invoice and save one history entry per serviced part.
        Returns the entries actually saved."""
        parts = self.__data.cars.list_parts(user.car_model)
        if not parts:
            self.__io.display_message("No service schedule is available for your car.")
            return []
        history = self.__data.history.for_plate(user.license_plate)
        invoice = self.__prompt_valid_invoice(user, history, parts, part_name)
        if invoice is None:
            return []

        saved_entries = []
        for name in invoice["part_names"]:
            saved = self.__save_invoice_part(user, history, invoice, name)
            if saved is not None:
                saved_entries.append(saved)

        if saved_entries:
            self.__io.display_message(f"\n{len(saved_entries)} service(s) added to your history:")
            for saved in saved_entries:
                self.__io.display_service(saved)
        return saved_entries

    def add(self, user: UserProfile) -> UserProfile:
        """Menu option 1."""
        self.add_services(user)
        return user

    # ---------- view ----------

    def view(self, user: UserProfile) -> UserProfile:
        """Menu option 2: services newest first, each with its latest assessment."""
        plate = user.license_plate
        entries = self.__rules.sort_history(self.__data.history.for_plate(plate))
        if not entries:
            self.__io.display_message(f"\nNo services in the history for {plate} yet. "
                                     "Choose 1 to add the services you've had done.")
            return user

        saved_checks = self.__data.checks.for_plate(plate)
        rows = []
        for entry in entries:
            row = dict(entry)            # a display copy; the saved entry is not changed
            row["latest_check"] = self.__rules.latest_check_for_service(saved_checks, entry)
            rows.append(row)
        self.__io.display_history(rows)
        return user

    # ---------- edit ----------

    def __edited_service_problem(self, user: UserProfile, entries: list[dict], chosen: dict,
                                updated: dict) -> str | None:
        """An edit must still fit the history and must not copy another entry."""
        problem = self.__service_problem(user, entries, updated["service_date"],
                                        updated["service_odometer"], chosen.get("service_id"))
        if problem is not None:
            return problem
        duplicate = self.__rules.find_duplicate_service(
            entries, updated["part_name"], updated["service_date"],
            updated["service_odometer"], chosen.get("service_id"),
            service_action=updated.get("service_action") or "unknown")
        if duplicate is not None:
            return "That would be an exact copy of a service already in your history."
        return None

    def edit(self, user: UserProfile) -> UserProfile:
        """Menu option 3: edit one saved service after validation."""
        entries = self.__rules.sort_history(self.__data.history.for_plate(user.license_plate))
        if not entries:
            self.__io.display_message("\nYour history is empty, so there is nothing to edit.")
            return user
        chosen = self.__io.prompt_service_choice(entries, "edit")
        if chosen is None:
            self.__io.display_message("Edit cancelled.")
            return user

        parts = self.__data.cars.list_parts(user.car_model)
        updated = self.__io.prompt_updated_service(chosen, parts, self.earliest_service_date(user))
        problem = self.__edited_service_problem(user, entries, chosen, updated)
        if problem is not None:
            self.__io.display_message(f"  -> {problem}\nNothing was changed.")
            return user
        if not self.__data.history.update(updated):
            self.__io.display_message("Could not save your changes. Please try again.")
            return user
        self.__io.display_message("\nService updated:")
        self.__io.display_service(updated)
        return user

    # ---------- delete ----------

    def delete(self, user: UserProfile) -> UserProfile:
        """Menu option 4: delete one saved service after confirmation."""
        entries = self.__rules.sort_history(self.__data.history.for_plate(user.license_plate))
        if not entries:
            self.__io.display_message("\nYour history is empty, so there is nothing to delete.")
            return user
        chosen = self.__io.prompt_service_choice(entries, "delete")
        if chosen is None:
            self.__io.display_message("Delete cancelled.")
            return user
        self.__io.display_service(chosen)
        if not self.__io.confirm_action("Delete this service from your history?"):
            self.__io.display_message("Delete cancelled.")
            return user
        # Delete by the unique service ID, not by the row number shown.
        if self.__data.history.delete(chosen.get("service_id")):
            self.__io.display_message("Service deleted.")
        else:
            self.__io.display_message("Could not delete the service. Please try again.")
        return user
