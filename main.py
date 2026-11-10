"""
main.py -- Car Maintenance & Service Risk Tracker. Run with: python main.py

Holds the App class, the only class that connects the four managers. It has no
business rules, file access or print()/input() of its own: the menu options are
handled by the controller classes in controllers/ (one class per file).
"""
from __future__ import annotations

import logging

from ai_manager import AIManager
from controllers.account_controller import AccountController
from controllers.check_controller import CheckController
from controllers.history_controller import HistoryController
from controllers.maintenance_pipeline import MaintenancePipeline
from data_manager import DataManager
from io_manager import IOManager
from logic.brake_history_analyser import BrakeHistoryAnalyser
from logic.history_rules import HistoryRules
from logic_manager import LogicManager


class App:
    """Builds the application and runs the menus until the user exits.

    AGGREGATION: the four managers are created outside and passed in, so each can be
    swapped (e.g. a test double) without changing App.
    COMPOSITION: App creates and owns its controllers and pipeline; they only exist
    inside the App."""

    # Menu choices after which the screen pauses so results stay visible.
    PAUSE_AFTER = ("1", "2", "3", "4", "5", "6", "7")

    def __init__(self, io: IOManager, data: DataManager, ai: AIManager, logic: LogicManager,
                 history_rules: HistoryRules | None = None):
        self.__io = io
        rules = history_rules or HistoryRules()
        pipeline = MaintenancePipeline(ai, logic)
        self.__accounts = AccountController(io, data, rules)
        self.__history = HistoryController(io, data, rules)
        self.__checks = CheckController(io, data, logic, rules, BrakeHistoryAnalyser(rules),
                                       pipeline, self.__history)
        self.__current_user = None
        # Menu choice -> action. Each action takes the user and returns the user who is
        # logged in afterwards (None = logged out). A new option is one new entry (OCP).
        self.__logged_in_actions = {
            "1": self.__history.add,
            "2": self.__history.view,
            "3": self.__history.edit,
            "4": self.__history.delete,
            "5": self.__checks.check_part,
            "6": self.__checks.urgent,
            "7": self.__accounts.show_profile,
            "8": self.__accounts.update_profile,
            "9": self.__accounts.delete_profile,
            "10": self.__accounts.logout,
        }

    @classmethod
    def create(cls) -> App:
        """The real application: console IO, JSON data files, live AI providers.
        Logging is set up first, so warnings while starting (e.g. a missing API key)
        use the same format as the rest of the app."""
        cls.__configure_logging()
        return cls(IOManager(), DataManager(), AIManager.from_env(), LogicManager())

    @staticmethod
    def __hide_google_notices(record: logging.LogRecord) -> bool:
        """Log filter: hide minor Google library notices, keep errors visible."""
        return not (record.name.startswith("google_genai") and record.levelno < logging.ERROR)

    @classmethod
    def __configure_logging(cls) -> None:
        logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(name)s: %(message)s")
        for handler in logging.getLogger().handlers:
            handler.addFilter(cls.__hide_google_notices)

    def __handle_logged_out(self, choice: str) -> bool:
        """Logged-out menu. Returns True when the user chose Exit."""
        if choice == "1":
            self.__current_user = self.__accounts.login()
        elif choice == "2":
            self.__current_user = self.__accounts.register()
        elif choice == "3":
            self.__io.display_message("Goodbye!")
            return True
        else:
            self.__io.display_message("Invalid choice. Please enter a number from the menu.")
        return False

    def __handle_logged_in(self, choice: str) -> bool:
        """Logged-in menu. Returns True when the user chose Exit."""
        if choice == "11":
            self.__io.display_message("Goodbye!")
            return True
        action = self.__logged_in_actions.get(choice)
        if action is None:
            self.__io.display_message("Invalid choice. Please enter a number from the menu.")
        else:
            self.__current_user = action(self.__current_user)
        if choice in self.PAUSE_AFTER:
            self.__io.wait_for_enter()
        return False

    def run(self) -> None:
        """Show the menu and handle choices until Exit (or Ctrl+C / end of input)."""
        try:
            while True:
                choice = self.__io.prompt_main_menu(self.__current_user)
                if self.__current_user is None:
                    should_exit = self.__handle_logged_out(choice)
                else:
                    should_exit = self.__handle_logged_in(choice)
                if should_exit:
                    break
        except (KeyboardInterrupt, EOFError):
            # Ctrl+C, or Docker run without -it: exit politely instead of crashing.
            self.__io.display_message("\nExiting. (If you're using Docker, run with: docker run -it ...)")


if __name__ == "__main__":
    App.create().run()
