"""GUI AI urgency checks and the urgent list. No AI provider: the pipeline falls back safely."""
import datetime

from fake_streamlit import FakeStreamlit
from gui.check_page import CheckPage
from gui.urgent_page import UrgentPage
from test_gui_data import GuiTestData, show


def add_oil_change(env):
    env.services.data.history.add({"license_plate": "SBA1234A", "part_name": "Engine Oil",
                                   "service_action": "replace", "service_date": "01-01-2025",
                                   "service_odometer": 30000, "notes": ""})


def test_check_without_history_asks_for_it_first():
    with GuiTestData() as env:
        user = env.add_user()
        ui = FakeStreamlit(inputs={"check_part": "Engine Oil"}, clicks={"check_button"})
        show(CheckPage(ui, env.services), ui, user)
        assert any("Add it on the Maintenance history page" in text
                   for text in ui.texts("warning"))


def test_check_runs_the_pipeline_then_reuses_a_repeated_result():
    with GuiTestData() as env:
        user = env.add_user()
        add_oil_change(env)
        answers = {"check_part": "Engine Oil", "check_km_Engine Oil": 50000}
        ui = FakeStreamlit(inputs=answers, clicks={"check_button"})
        show(CheckPage(ui, env.services), ui, user)
        # No AI provider in the tests: the pipeline falls back safely (C2).
        assert "NEEDS MANUAL REVIEW - AI assessment unavailable" in ui.texts("error")
        assert len(env.services.data.checks.for_plate("SBA1234A")) == 1

        ui = FakeStreamlit(inputs=answers, clicks={"check_button"})
        show(CheckPage(ui, env.services), ui, user)
        assert any("repeated information" in text for text in ui.texts("info"))
        assert len(env.services.data.checks.for_plate("SBA1234A")) == 1   # AI not asked


def test_urgent_page_lists_open_items_and_hides_superseded_ones():
    with GuiTestData() as env:
        user = env.add_user()
        add_oil_change(env)
        ui = FakeStreamlit(inputs={"check_part": "Engine Oil", "check_km_Engine Oil": 50000},
                           clicks={"check_button"})
        show(CheckPage(ui, env.services), ui, user)
        ui = FakeStreamlit()
        show(UrgentPage(ui, env.services), ui, user)
        assert ui.texts("dataframe")[0][0]["Part"] == "Engine Oil"

        env.services.data.history.add({"license_plate": "SBA1234A", "part_name": "Engine Oil",
                                       "service_action": "replace",
                                       "service_date": datetime.date.today().strftime("%d-%m-%Y"),
                                       "service_odometer": 50000, "notes": ""})
        ui = FakeStreamlit()
        show(UrgentPage(ui, env.services), ui, user)
        assert any("Nothing needs attention" in text for text in ui.texts("success"))