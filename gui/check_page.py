"""
CheckPage: check one part with the AI, like menu option 5. The record is built by the
shared CheckRecordBuilder and sent through MaintenancePipeline (AI first, then the
business rules, C2). Identical inputs reuse the saved result instead of the AI (C4).
"""
from __future__ import annotations

import datetime

from gui.gui_page import GuiPage
from io_manager import IOManager
from models.user_profile import UserProfile


class CheckPage(GuiPage):
    """INHERITANCE: a GuiPage. The last result is kept in the session, so it stays on
    screen when Streamlit redraws the page."""

    RESULT_KEY = "check_result"

    @property
    def title(self) -> str:
        return "AI urgency check"

    def render(self, user: UserProfile | None) -> None:
        ui, data, rules = self._ui, self._services.data, self._services.rules
        ui.subheader("Check a part with the AI")
        manual_path = data.cars.get_manual_path(user.car_model)
        parts = data.cars.list_parts(user.car_model)
        if manual_path is None or not parts:
            ui.error(f"The manual or service schedule for {user.car_model} is missing, "
                     "so parts can't be checked.")
            return
        part = ui.selectbox("Part", parts, key="check_part")
        interval = data.cars.get_service_interval(user.car_model, part)
        history = data.history.for_plate(user.license_plate)
        model_year = self._model_year(user)
        last = rules.latest_service(history, part, interval.get("action", "replace"), model_year)
        if last is None and "repeat_km" in interval and model_year is not None and ui.checkbox(
                f"My {part} has never been replaced (count from new)", key="check_from_new"):
            last = rules.from_new_service(part, model_year)
        if last is None:
            ui.warning(f"There is no confirmed {part} service that resets this interval yet. "
                       "Add it on the Maintenance history page first.")
            return
        ui.caption(f"Using the last service: {last['service_date']} at "
                   f"{IOManager.km(last['service_odometer'])} km "
                   f"({last.get('service_action') or 'from new'})")

        # Business rule 1 and the km-per-day limit decide the allowed odometer range.
        lowest = max(last["service_odometer"], data.last_odometer_on_file(user.license_plate) or 0)
        highest = IOManager.MAX_ODOMETER_KM
        reading = rules.latest_reading(history, data.checks.for_plate(user.license_plate))
        if reading is not None:
            highest = rules.max_plausible_odometer(reading[0], reading[1], datetime.date.today())
        odometer = int(ui.number_input("Current odometer reading (km)", min_value=lowest,
                                       max_value=max(highest, lowest), value=lowest, step=1,
                                       key=f"check_km_{part}"))   # one box per part
        if ui.button("Ask the AI", key="check_button"):
            part_services = [entry for entry in history if entry.get("part_name") == part]
            record = self._services.record_builder.build(
                user, part, last, odometer, rules.choose_interval(interval, part_services),
                model_year)
            self.__assess(record, manual_path)
        saved = ui.session_state.get(self.RESULT_KEY)
        if saved and saved[0].get("license_plate") == user.license_plate:
            self.__show(*saved)

    def __assess(self, record: dict, manual_path: str) -> None:
        data = self._services.data
        previous = data.checks.find_repeat(record)
        if previous is not None:
            self._ui.session_state[self.RESULT_KEY] = (previous, True)
            return
        with self._ui.spinner("Asking the AI to check this part against your manual..."):
            final = self._services.pipeline.assess(record, manual_path)
        if not data.checks.save(final):
            self._ui.warning("The assessment could not be saved to disk.")
        self._ui.session_state[self.RESULT_KEY] = (final, False)

    def __show(self, record: dict, repeated: bool) -> None:
        ui = self._ui
        if repeated:
            ui.info("This is repeated information: you checked this part with the same details "
                    f"on {record.get('check_date')}, so the AI was not asked again.")
        outcome = str(record.get("outcome"))
        if self._services.logic.is_urgent(record):
            ui.error(outcome)
        elif outcome.startswith("OK"):
            ui.success(outcome)
        else:
            ui.warning(outcome)
        urgency = record.get("urgency_score")
        first, second, third = ui.columns(3)
        first.metric("AI urgency", "n/a" if urgency is None else f"{urgency}/10")
        second.metric("Risk score", f"{record.get('risk_score')}/100")
        third.metric("Service by", IOManager.show_date(record.get("recommended_service_date")))
        details = [
            ("Part", record.get("part_name")),
            ("Schedule", IOManager.schedule_text(record)),
            ("Since last service", f"{IOManager.km(record.get('km_since_service'))} km / "
                                   f"{record.get('days_since_service')} days"),
            ("AI confidence", record.get("confidence")),
            ("Answered by", record.get("ai_provider", "n/a")),
            ("AI summary", record.get("overdue_summary")),
            ("Manual reference", record.get("manual_reference")),
            ("Advice", record.get("recommended_action")),
        ]
        if record.get("history_pattern"):
            details.append(("Brake history pattern", record.get("history_pattern")))
        ui.dataframe([{"Detail": label, "Value": str(value)} for label, value in details],
                     hide_index=True)