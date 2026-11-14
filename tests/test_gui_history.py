"""GUI maintenance history: the same HistoryRules checks as the terminal app."""
import datetime

from fake_streamlit import FakeStreamlit
from gui.history_page import HistoryPage
from test_gui_data import GuiTestData, show


def test_history_adds_one_invoice_for_several_parts_and_skips_duplicates():
    with GuiTestData() as env:
        user = env.add_user()
        answers = {"add_parts": ["Engine Oil", "Tyres"], "add_action_Engine Oil": "replace",
                   "add_action_Tyres": "rotate", "add_date": datetime.date(2025, 3, 1),
                   "add_km": 30000, "add_notes": "Ah Seng Motors"}
        ui = FakeStreamlit(inputs=answers, clicks={"add_save"})
        assert show(HistoryPage(ui, env.services), ui, user)
        assert ui.session_state["flash"] == "2 service(s) added: Engine Oil, Tyres."
        saved = env.services.data.history.for_plate("SBA1234A")
        assert {entry["service_action"] for entry in saved} == {"replace", "rotate"}

        ui = FakeStreamlit(inputs=answers, clicks={"add_save"})     # the same invoice again
        assert show(HistoryPage(ui, env.services), ui, user)
        assert "not added again: Engine Oil, Tyres" in ui.session_state["flash"]
        assert len(env.services.data.history.for_plate("SBA1234A")) == 2


def test_history_refuses_an_odometer_that_goes_backwards():
    with GuiTestData() as env:
        user = env.add_user()
        env.services.data.history.add({"license_plate": "SBA1234A", "part_name": "Coolant",
                                       "service_action": "inspect", "service_date": "01-01-2025",
                                       "service_odometer": 40000, "notes": ""})
        ui = FakeStreamlit(inputs={"add_parts": ["Engine Oil"],
                                   "add_date": datetime.date(2025, 6, 1), "add_km": 30000},
                           clicks={"add_save"})
        assert not show(HistoryPage(ui, env.services), ui, user)
        assert any("odometer went backwards" in text for text in ui.texts("error"))
        assert len(env.services.data.history.for_plate("SBA1234A")) == 1


def test_history_delete_needs_the_tick_box():
    with GuiTestData() as env:
        user = env.add_user()
        env.services.data.history.add({"license_plate": "SBA1234A", "part_name": "Coolant",
                                       "service_action": "inspect", "service_date": "01-01-2025",
                                       "service_odometer": 40000, "notes": ""})
        ui = FakeStreamlit(clicks={"delete_button"})
        show(HistoryPage(ui, env.services), ui, user)
        assert len(env.services.data.history.for_plate("SBA1234A")) == 1
        ui = FakeStreamlit(inputs={"delete_sure": True}, clicks={"delete_button"})
        assert show(HistoryPage(ui, env.services), ui, user)
        assert env.services.data.history.for_plate("SBA1234A") == []