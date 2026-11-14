"""
HistoryPage: the maintenance history as a table, adding one workshop invoice (it can
cover several parts) and deleting a service. The same HistoryRules checks as the
terminal app: odometer never goes backwards, km-per-day limit, no duplicates.
"""
from __future__ import annotations

import datetime

from gui.gui_page import GuiPage
from io_manager import IOManager
from models.user_profile import UserProfile


class HistoryPage(GuiPage):
    """INHERITANCE: a GuiPage for maintenance history CRUD."""

    @property
    def title(self) -> str:
        return "Maintenance history"

    def render(self, user: UserProfile | None) -> None:
        self._ui.subheader("Maintenance history")
        history = self._services.rules.sort_history(
            self._services.data.history.for_plate(user.license_plate))
        if history:
            self._ui.dataframe(self.__rows(user, history), hide_index=True)
        else:
            self._ui.info("No services yet. Add the services from your workshop invoices below.")
        self.__add(user, history)
        if history:
            self.__delete(history)

    def __rows(self, user: UserProfile, history: list[dict]) -> list[dict]:
        """One table row per service, with the newest AI check based on it."""
        checks = self._services.data.checks.for_plate(user.license_plate)
        rows = []
        for entry in history:
            check = self._services.rules.latest_check_for_service(checks, entry) or {}
            rows.append({
                "Serviced": IOManager.show_date(entry.get("service_date")),
                "Part": entry.get("part_name"),
                "Action": entry.get("service_action") or "unknown",
                "Odometer (km)": IOManager.km(entry.get("service_odometer")),
                "Urgency": str(check.get("urgency_score", "-")),
                "Outcome": str(check.get("outcome", "not checked yet")).split(" - ")[0],
                "Notes": entry.get("notes") or "",
            })
        return rows

    @staticmethod
    def __actions_for(part_name: str) -> list[str]:
        """What can be done to a part. Business rule: only tyres are rotated."""
        return ["inspect", "replace", "rotate"] if part_name == "Tyres" else ["inspect", "replace"]

    def __add(self, user: UserProfile, history: list[dict]) -> None:
        ui, data, rules = self._ui, self._services.data, self._services.rules
        ui.subheader("Add a workshop invoice")
        parts = ui.multiselect("Parts serviced on this invoice",
                               data.cars.list_parts(user.car_model), key="add_parts")
        actions = {part: ui.selectbox(f"What was done to {part}?", self.__actions_for(part),
                                      index=1, key=f"add_action_{part}") for part in parts}
        today = datetime.date.today()
        service_date = ui.date_input("Service date", value=today,
                                     min_value=self._earliest_date(user), max_value=today,
                                     format="DD-MM-YYYY", key="add_date")
        odometer = int(ui.number_input("Odometer at service (km)", min_value=0,
                                       max_value=IOManager.MAX_ODOMETER_KM, step=1,
                                       value=data.last_odometer_on_file(user.license_plate) or 0,
                                       key="add_km"))
        notes = ui.text_input("Workshop / notes (optional)", key="add_notes")
        if not ui.button("Save invoice", key="add_save", disabled=not parts):
            return

        date_text = self._text_date(service_date)
        problem = (rules.check_service_odometer(history, date_text, odometer)
                   or rules.check_service_pace(history, date_text, odometer,
                                               self._model_year(user)))
        if problem:
            ui.error(problem)
            return
        saved, skipped = [], []
        for part in parts:
            if rules.find_duplicate_service(history, part, date_text, odometer,
                                            service_action=actions[part]) is not None:
                skipped.append(part)
                continue
            entry = {"license_plate": user.license_plate, "part_name": part,
                     "service_action": actions[part], "service_date": date_text,
                     "service_odometer": odometer, "notes": notes.strip()}
            if data.history.add(entry) is None:
                ui.error(f"Could not save the {part} service. Please try again.")
                return
            saved.append(part)
        message = f"{len(saved)} service(s) added: {', '.join(saved)}." if saved else ""
        if skipped:
            message += f" Already in your history, so not added again: {', '.join(skipped)}."
        self._finish(message.strip())

    def __delete(self, history: list[dict]) -> None:
        ui = self._ui
        ui.subheader("Delete a service")
        labels = [f"#{entry.get('service_id')}  {entry.get('service_date')}  "
                  f"{entry.get('part_name')}  {IOManager.km(entry.get('service_odometer'))} km"
                  for entry in history]
        chosen = history[labels.index(ui.selectbox("Service", labels, key="delete_service"))]
        sure = ui.checkbox("Yes, delete this service", key="delete_sure")
        if not ui.button("Delete service", key="delete_button", disabled=not sure):
            return
        # Delete by the unique service ID, not by the position in the list.
        if self._services.data.history.delete(chosen.get("service_id")):
            self._finish("Service deleted.")
        else:
            ui.error("Could not delete the service. Please try again.")