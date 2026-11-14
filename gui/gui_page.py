"""
<<abstract>> GuiPage: one page of the Streamlit GUI. StreamlitGui only calls title and
render() on each page, whichever page it is (polymorphism). The GUI is a second
input/output layer next to the terminal IOManager; both use the same managers.
"""
from __future__ import annotations

import datetime
from abc import ABC, abstractmethod

from gui.gui_services import GuiServices
from models.user_profile import UserProfile


class GuiPage(ABC):
    """ABSTRACT CLASS: shared set-up and helpers; each page implements render()."""

    DATE_FORMAT = "%d-%m-%Y"        # how dates are saved, as in the terminal app
    USER_KEY = "user"               # session key: the logged-in UserProfile
    FLASH_KEY = "flash"             # session key: a message to show after a redraw

    def __init__(self, ui, services: GuiServices):
        # PROTECTED (#): the page subclasses draw with _ui and use _services.
        self._ui = ui                  # the streamlit module (a fake one in the tests)
        self._services = services      # aggregation: shared by every page

    @property
    @abstractmethod
    def title(self) -> str:
        """The page name shown in the sidebar."""

    @abstractmethod
    def render(self, user: UserProfile | None) -> None:
        """Draw the page for the logged-in user (None before logging in)."""

    def _finish(self, message: str | None = None) -> None:
        """Keep a success message for the next run, then redraw the page. Streamlit
        re-runs the script, so a message shown now would disappear straight away."""
        if message:
            self._ui.session_state[self.FLASH_KEY] = message
        self._ui.rerun()

    def _model_year(self, user: UserProfile) -> int | None:
        """The car's model year, via the associated Car when there is one."""
        if user.car is not None:
            return user.car.model_year
        return self._services.data.cars.get_model_year(user.car_model)

    def _earliest_date(self, user: UserProfile) -> datetime.date | None:
        """1 January of the model year: nothing can be dated before the car was made."""
        year = self._model_year(user)
        return None if year is None else datetime.date(year, 1, 1)

    @classmethod
    def _text_date(cls, value: datetime.date) -> str:
        """A date from a date picker as saved DD-MM-YYYY text."""
        return value.strftime(cls.DATE_FORMAT)

    @classmethod
    def _parse_date(cls, text) -> datetime.date | None:
        """Saved DD-MM-YYYY text as a date (None if missing or damaged)."""
        try:
            return datetime.datetime.strptime(str(text), cls.DATE_FORMAT).date()
        except ValueError:
            return None