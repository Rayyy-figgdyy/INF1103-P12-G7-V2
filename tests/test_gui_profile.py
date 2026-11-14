"""GUI profile page: updates go through UserProfile's checked setters."""
import datetime

from fake_streamlit import FakeStreamlit
from gui.profile_page import ProfilePage
from test_gui_data import GuiTestData, show


def test_profile_update_uses_the_checked_setters():
    with GuiTestData() as env:
        user = env.add_user()
        ui = FakeStreamlit(inputs={"profile_name": "   "}, clicks={"profile_save"})
        assert not show(ProfilePage(ui, env.services), ui, user)
        assert "Name cannot be empty." in ui.texts("error")

        ui = FakeStreamlit(inputs={"profile_name": "Darren Ng",
                                   "profile_coe": datetime.date(2031, 6, 30)},
                           clicks={"profile_save"})
        assert show(ProfilePage(ui, env.services), ui, user)
        saved = env.services.data.users.find_by_plate("SBA1234A")
        assert saved.name == "Darren Ng" and saved.coe_expiry_date == "30-06-2031"


def test_profile_delete_needs_the_tick_box_and_logs_out():
    with GuiTestData() as env:
        user = env.add_user()
        ui = FakeStreamlit(clicks={"profile_delete"})          # box not ticked
        assert not show(ProfilePage(ui, env.services), ui, user)
        assert env.services.data.users.find_by_plate("SBA1234A") is not None

        ui = FakeStreamlit(inputs={"profile_delete_sure": True}, clicks={"profile_delete"},
                           session_state={"user": user})
        assert show(ProfilePage(ui, env.services), ui, user)
        assert env.services.data.users.find_by_plate("SBA1234A") is None
        assert "user" not in ui.session_state