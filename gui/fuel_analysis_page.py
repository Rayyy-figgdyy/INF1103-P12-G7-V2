"""
FuelAnalysisPage: ask the AI to assess fuel economy (the team's FuelService decides
whether a saved report can be reused), and review an open AI fuel alert.
"""
from __future__ import annotations

from gui.gui_page import GuiPage
from models.user_profile import UserProfile


class FuelAnalysisPage(GuiPage):
    """INHERITANCE: a GuiPage. The AI is only asked when the button is pressed."""

    RESULT_KEY = "fuel_result"
    DECISIONS = {
        "ordinary_variation": "Ordinary variation: keep these readings for future comparisons",
        "confirmed_fault": "Confirmed fault period: exclude it from the comparison average",
        "changed_conditions": "Changed driving conditions: start a new comparison average",
    }

    @property
    def title(self) -> str:
        return "Fuel AI analysis"

    def render(self, user: UserProfile | None) -> None:
        ui, fuel = self._ui, self._services.fuel
        ui.subheader("Fuel efficiency analysis with AI")
        dashboard = fuel.get_dashboard(user.license_plate, user.car_model)
        problem = dashboard["analysis_problem"]
        if problem:
            ui.info(problem)
        else:
            comparison, recent, change = ui.columns(3)
            comparison.metric("Comparison average", f"{dashboard['baseline_km_per_l']:.2f} km/L")
            recent.metric("Last 3 intervals", f"{dashboard['recent_average_km_per_l']:.2f} km/L")
            change.metric("Change", f"{-dashboard['recent_drop_percent']:+.1f}%")
        if ui.button("Analyse with AI", key="fuel_analyse", disabled=bool(problem)):
            with ui.spinner("Asking the AI to assess your fuel economy..."):
                result = fuel.analyse_with_ai(user.license_plate, self._services.ai,
                                              user.car_model, self._services.logic)
            ui.session_state[self.RESULT_KEY] = (user.license_plate, result)
            dashboard = fuel.get_dashboard(user.license_plate, user.car_model)
        saved = ui.session_state.get(self.RESULT_KEY)
        if saved and saved[0] == user.license_plate:
            self.__show(saved[1])
        if dashboard["alert_active"]:
            self.__review(user, dashboard["alert"])

    def __show(self, result: dict) -> None:
        ui = self._ui
        if result.get("ai_status") == "insufficient_history":
            ui.info(result.get("message"))
            return
        if result.get("ai_status") != "ok":
            ui.error(f"AI report unavailable: {result.get('message', 'Please try again.')}")
            ui.caption(result.get("fuel_outcome", ""))
            return
        if result.get("reused"):
            ui.info("Report previously generated. No data has changed, "
                    "so the saved report is shown.")
        status = result["anomaly_status"]
        box = {"Normal": ui.success, "Unusual drop": ui.error}.get(status, ui.warning)
        box(f"Assessment: {status} ({result.get('pattern', 'Unclear').lower()} pattern, "
            f"confidence {result.get('confidence')})")
        ui.write(result.get("summary", ""))
        if status != "Normal" and result.get("possible_factors"):
            ui.markdown("Possible explanations (unconfirmed):\n"
                        + "\n".join(f"- {factor}" for factor in result["possible_factors"]))
        steps = [result.get("fuel_outcome", "")]
        if status != "Normal":
            steps.extend(result.get("suggested_checks", []))
        ui.markdown("Next steps:\n"
                    + "\n".join(f"- {step}" for step in dict.fromkeys(steps) if step))
        ui.caption(f"Answered by: {result.get('ai_provider', 'n/a')}")

    def __review(self, user: UserProfile, alert: dict) -> None:
        ui = self._ui
        ui.subheader("Review the open fuel alert")
        ui.caption(f"Alert period: {alert['first_date']} to {alert['last_date']}. Correct any "
                   "mistaken refuels first; this decision applies to the whole period.")
        decision = ui.radio("Your decision", list(self.DECISIONS),
                            format_func=self.DECISIONS.get, key="fuel_review_decision")
        if not ui.button("Save review", key="fuel_review_save"):
            return
        try:
            self._services.fuel.review_alert(user.license_plate, decision)
        except (ValueError, OSError) as error:
            ui.error(f"Could not save the review: {error}")
            return
        ui.session_state.pop(self.RESULT_KEY, None)      # the old report no longer applies
        self._finish("Review saved. All original fuel records are kept.")