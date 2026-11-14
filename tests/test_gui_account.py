"""GUI login and registration, tested with the fake Streamlit (no browser needed)."""
import datetime

from fake_streamlit import FakeStreamlit
from gui.account_page import AccountPage
from test_gui_data import CAR, GuiTestData, show


def test_register_creates_profile_and_logs_in():
    with GuiTestData() as env:
        ui = FakeStreamlit(inputs={"register_name": "Darren", "register_plate": "sba 1234-a",
                                   "register_car": CAR,
                                   f"register_coe_{CAR}": datetime.date(2030, 1, 1)},
                           clicks={"register_button"})
        assert show(AccountPage(ui, env.services), ui)
        user = ui.session_state["user"]
        assert user.license_plate == "SBA1234A" and user.car is not None
        assert env.services.data.users.find_by_plate("SBA1234A").coe_expiry_date == "01-01-2030"


def test_register_rejects_bad_and_taken_plates():
    with GuiTestData() as env:
        env.add_user("SBA1234A")
        for plate, message in (("12345", "must look like"), ("SBA1234A", "already registered")):
            ui = FakeStreamlit(inputs={"register_name": "Ann", "register_plate": plate,
                                       "register_car": CAR}, clicks={"register_button"})
            assert not show(AccountPage(ui, env.services), ui)
            assert any(message in text for text in ui.texts("error"))
            assert "user" not in ui.session_state


def test_login_known_and_unknown_plates():
    with GuiTestData() as env:
        env.add_user("SBA1234A")
        ui = FakeStreamlit(inputs={"login_plate": "SZZ9999Z"}, clicks={"login_button"})
        assert not show(AccountPage(ui, env.services), ui)
        assert ui.texts("error") and "user" not in ui.session_state

        ui = FakeStreamlit(inputs={"login_plate": "sba1234a"}, clicks={"login_button"})
        assert show(AccountPage(ui, env.services), ui)
        assert ui.session_state["user"].name == "Darren"
        assert ui.session_state["flash"] == "Welcome back, Darren!"