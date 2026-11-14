"""
UrgentPage: each part's latest AI check that still needs attention, most serious
first (like menu option 6). A check drops off once a newer service supersedes it.
"""
from __future__ import annotations

from gui.gui_page import GuiPage
from io_manager import IOManager
from models.user_profile import UserProfile


class UrgentPage(GuiPage):
    """INHERITANCE: a GuiPage that only reads saved checks; it never calls the AI."""

    @property
    def title(self) -> str:
        return "Urgent items"

    def render(self, user: UserProfile | None) -> None:
        data, rules, logic = self._services.data, self._services.rules, self._services.logic
        self._ui.subheader("Parts that need attention")
        history = data.history.for_plate(user.license_plate)
        urgent = [record for record in rules.latest_check_per_part(
                      data.checks.for_plate(user.license_plate))
                  if not rules.is_check_superseded(record, history) and logic.is_urgent(record)]
        if not urgent:
            self._ui.success("Nothing needs attention right now: none of your parts' latest "
                             "checks are urgent, flagged, overdue or waiting for manual review.")
            return
        urgent.sort(key=lambda record: record.get("risk_score", 0), reverse=True)
        self._ui.dataframe([{
            "Part": record.get("part_name"),
            "Outcome": record.get("outcome"),
            "Urgency": str(record.get("urgency_score") or "-"),
            "Risk score": record.get("risk_score", 0),
            "Service by": IOManager.show_date(record.get("recommended_service_date")),
            "Checked": IOManager.show_date(record.get("check_date")),
            "Odometer (km)": IOManager.km(record.get("current_odometer")),
        } for record in urgent], hide_index=True)