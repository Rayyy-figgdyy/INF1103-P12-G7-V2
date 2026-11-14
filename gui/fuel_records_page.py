"""
FuelRecordsPage: full-tank refuels as a table and a km/L chart, adding and deleting
refuels. All checks and calculations come from the team's FuelService.
"""
from __future__ import annotations

import datetime

from gui.gui_page import GuiPage
from io_manager import IOManager
from models.fuel_entry import FuelEntry
from models.user_profile import UserProfile


class FuelRecordsPage(GuiPage):
    """INHERITANCE: a GuiPage. Saving a refuel never calls the AI."""

    @property
    def title(self) -> str:
        return "Fuel records"

    def render(self, user: UserProfile | None) -> None:
        self._ui.subheader("Fuel consumption")
        self._ui.caption("Record FULL-tank refuels only, with no partial fills between them. "
                         "Use the same stopping level each time, such as the first pump cut-off.")
        dashboard = self._services.fuel.get_dashboard(user.license_plate, user.car_model)
        self.__summary(dashboard)
        self.__add(user, dashboard)
        if dashboard["refuel_history"]:
            self.__delete(user, dashboard)

    def __summary(self, dashboard: dict) -> None:
        ui = self._ui
        if not dashboard["refuel_history"]:
            ui.info("No fuel records yet.")
            return
        points = {point["entry_id"]: point for point in dashboard["chart_points"]}
        rows = []
        for entry in dashboard["refuel_history"]:
            point = points.get(entry["entry_id"], {})   # none for a starting refuel
            rows.append({"Date": entry["refuel_date"],
                         "Odometer (km)": IOManager.km(entry["odometer_km"]),
                         "Litres": f"{entry['litres']:.2f}",
                         "Interval km/L": self.__km_per_l(point.get("actual_km_per_l")),
                         "Running avg km/L": self.__km_per_l(
                             point.get("running_average_km_per_l"))})
        ui.dataframe(rows, hide_index=True)
        if not points:
            ui.caption("Your first full refuel sets the starting odometer. "
                       "Add another full refuel to measure km/L.")
            return
        latest, overall, comparison = ui.columns(3)
        latest.metric("Latest interval", f"{dashboard['latest_km_per_l']:.2f} km/L")
        overall.metric("Average of all intervals",
                       f"{dashboard['overall_average_km_per_l']:.2f} km/L")
        baseline = dashboard.get("baseline_km_per_l")
        comparison.metric("Comparison average",
                          "More history needed" if baseline is None else f"{baseline:.2f} km/L")
        chart = dashboard["chart_points"]
        ui.line_chart({"Refuel": list(range(1, len(chart) + 1)),
                       "Interval km/L": [point["actual_km_per_l"] for point in chart],
                       "Running average km/L": [point["running_average_km_per_l"]
                                                for point in chart]},
                      x="Refuel", y=["Interval km/L", "Running average km/L"])

    @staticmethod
    def __km_per_l(value) -> str:
        """A table cell: '-' for a starting refuel, so every cell in the column is text."""
        return "-" if value is None else f"{value:.2f}"

    def __add(self, user: UserProfile, dashboard: dict) -> None:
        ui = self._ui
        ui.subheader("Add a full-tank refuel")
        history = dashboard["refuel_history"]
        last_km = history[-1]["odometer_km"] if history else (
            self._services.data.last_odometer_on_file(user.license_plate) or 0)
        today = datetime.date.today()
        refuel_date = ui.date_input("Refuel date", value=today, max_value=today,
                                    format="DD-MM-YYYY", key="fuel_date")
        odometer = int(ui.number_input("Odometer (km)", min_value=0,
                                       max_value=FuelEntry.MAX_ODOMETER_KM, value=last_km,
                                       step=1, key="fuel_km"))
        litres = float(ui.number_input("Fuel pumped (litres)", min_value=0.1, max_value=200.0,
                                       value=40.0, step=0.1, key="fuel_litres"))
        if not ui.button("Save refuel", key="fuel_save"):
            return
        try:
            saved = self._services.fuel.add_refuel(user.license_plate,
                                                   self._text_date(refuel_date), odometer, litres)
        except (ValueError, OSError) as error:    # FuelEntry and FuelService explain the problem
            ui.error(f"Could not add refuel: {error}")
            return
        self._finish(f"Saved full-tank refuel #{saved.entry_id}.")

    def __delete(self, user: UserProfile, dashboard: dict) -> None:
        ui = self._ui
        ui.subheader("Delete a refuel")
        history = dashboard["refuel_history"]
        labels = [f"#{entry['entry_id']}  {entry['refuel_date']}  "
                  f"{IOManager.km(entry['odometer_km'])} km" for entry in history]
        chosen = history[labels.index(ui.selectbox("Refuel", labels, key="fuel_delete_choice"))]
        sure = ui.checkbox("Yes, delete this refuel", key="fuel_delete_sure")
        if not ui.button("Delete refuel", key="fuel_delete", disabled=not sure):
            return
        if self._services.fuel.delete_refuel(user.license_plate, chosen["entry_id"]):
            self._finish("Deleted. Measurement restarts at the next recorded full tank.")
        else:
            ui.error("Could not delete the fuel record.")