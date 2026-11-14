"""
streamlit_app.py -- the web GUI. Run with:  streamlit run streamlit_app.py
The terminal app (python main.py) still works; both use the same data files.
"""
from __future__ import annotations

import logging

from gui.account_page import AccountPage
from gui.gui_page import GuiPage
from gui.gui_services import GuiServices
from gui.history_page import HistoryPage
from gui.check_page import CheckPage
from gui.profile_page import ProfilePage


class StreamlitGui:
    """Runs the GUI. Streamlit re-runs this whole file after every click, so the
    services and the logged-in user are kept in session_state between runs.
    COMPOSITION: the pages are created here and owned by the GUI.
    POLYMORPHISM: run() only uses title and render(), whichever page is chosen."""

    SERVICES_KEY = "services"

    def __init__(self, ui, services: GuiServices):
        self.__ui = ui
        self.__account = AccountPage(ui, services)
        # A new page is one more object in this list; run() doesn't change (OCP).
        self.__pages: list[GuiPage] = [
            HistoryPage(ui, services), CheckPage(ui, services), ProfilePage(ui, services)]

    @classmethod
    def create(cls, ui=None) -> StreamlitGui:
        """Reuse this browser session's services, or build them on the first run."""
        if ui is None:
            import streamlit as ui      # imported here so the tests don't need Streamlit
        if cls.SERVICES_KEY not in ui.session_state:
            logging.basicConfig(level=logging.WARNING,
                                format="[%(levelname)s] %(name)s: %(message)s")
            ui.session_state[cls.SERVICES_KEY] = GuiServices()
        return cls(ui, ui.session_state[cls.SERVICES_KEY])

    def run(self) -> None:
        ui = self.__ui
        ui.set_page_config(page_title="Car Maintenance Tracker", layout="wide")
        ui.title("Car Maintenance & Service Risk Tracker")
        flash = ui.session_state.pop(GuiPage.FLASH_KEY, None)
        if flash:
            ui.success(flash)

        user = ui.session_state.get(GuiPage.USER_KEY)
        if user is None:
            self.__account.render(None)
            return

        ui.sidebar.write(f"Logged in: {user.name}")
        ui.sidebar.caption(f"{user.license_plate} | {user.car_model}")
        titles = [page.title for page in self.__pages]
        chosen = ui.sidebar.radio("Go to", titles, key="page")
        if ui.sidebar.button("Log out", key="logout"):
            ui.session_state.pop(GuiPage.USER_KEY, None)
            ui.rerun()
        self.__pages[titles.index(chosen)].render(user)


if __name__ == "__main__":
    StreamlitGui.create().run()