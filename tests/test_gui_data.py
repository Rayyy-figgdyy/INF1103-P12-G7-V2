"""
Shared set-up for the GUI tests: a temporary data folder with the real car list,
GuiServices built on it, and show() to render a page with the fake Streamlit.
"""
import os
import shutil
import tempfile

from ai.fuel_ai_manager import FuelAIManager
from fake_streamlit import RerunRequested
from gui.gui_services import GuiServices
from logic.fuel_logic_manager import FuelLogicManager
from models.user_profile import UserProfile
from storage.fuel_data_manager import FuelDataManager

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAR = "Hyundai Elantra 2021"


class GuiTestData:
    """A temporary data folder with the real car list, and GuiServices using it.
    Without providers, an AI request falls back safely without a network."""

    def __init__(self, providers=()):
        self.providers = list(providers)

    def __enter__(self):
        self.folder = tempfile.mkdtemp()
        shutil.copy(os.path.join(PROJECT_ROOT, "data", "cars.json"), self.folder)
        data = FuelDataManager(data_dir=self.folder, project_dir=PROJECT_ROOT)
        ai = FuelAIManager(self.providers, retry_delay=0)
        self.services = GuiServices(data, ai, FuelLogicManager())
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.folder)
        return False

    def add_user(self, plate="SBA1234A", name="Darren") -> UserProfile:
        user = UserProfile(name, plate, CAR, "Used", "01-01-2030")
        assert self.services.data.users.save(user)
        user.attach_car(self.services.data.cars.find(CAR))
        return user


def show(page, ui, user=None) -> bool:
    """Render a page; True if it asked Streamlit to redraw (rerun)."""
    try:
        page.render(user)
    except RerunRequested:
        return True
    return False