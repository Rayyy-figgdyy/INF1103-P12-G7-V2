"""The StreamlitGui shell: the login page until someone logs in, then the chosen page."""
from fake_streamlit import FakeStreamlit
from test_gui_data import GuiTestData
from streamlit_app import StreamlitGui


def test_app_shows_login_until_logged_in_then_the_chosen_page():
    with GuiTestData() as env:
        ui = FakeStreamlit(session_state={"services": env.services})
        StreamlitGui.create(ui).run()
        assert ["Log in", "Register"] in ui.texts("tabs")            # the account page
        assert not any("Logged in" in str(text) for text in ui.texts("write"))

        user = env.add_user()
        ui = FakeStreamlit(inputs={"page": "My profile"},
                           session_state={"services": env.services, "user": user,
                                          "flash": "Welcome back, Darren!"})
        StreamlitGui.create(ui).run()
        assert "Welcome back, Darren!" in ui.texts("success")
        assert "My profile" in ui.texts("subheader")              # the page chosen
        assert "flash" not in ui.session_state                  # shown once only