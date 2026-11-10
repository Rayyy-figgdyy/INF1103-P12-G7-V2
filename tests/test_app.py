"""
Integration test: drives the whole App through a scripted session (register, add,
view, edit and delete history, an AI check, the urgent list, update and delete the
profile) so every controller method runs at least once. No AI provider is given, so
the check takes the safe fallback path ("NEEDS MANUAL REVIEW") without a network.
"""
import os
import shutil
import tempfile

from ai_manager import AIManager
from data_manager import DataManager
from io_manager import IOManager
from logic_manager import LogicManager
from main import App

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SESSION = [
    "2", "Test User", "sbx1234z", "3", "01-01-2030",       # register (Hyundai Elantra 2021)
    "1", "4", "2", "01-02-2025", "30000", "Shop A", "",     # add: Engine Oil replaced
    "2", "",                                                # view history
    "5", "4", "40000", "",                                  # check Engine Oil
    "6", "",                                                # urgent list
    "7", "",                                                # view profile
    "8", "New Name", "",                                    # update profile (keep COE)
    "3", "1", "", "", "", "31000", "", "",                  # edit the service's odometer
    "4", "1", "y", "",                                      # delete the service
    "9", "y",                                               # delete the profile
    "3",                                                    # exit
]


def test_full_session_runs_end_to_end(monkeypatch, capsys):
    data_dir = tempfile.mkdtemp()
    try:
        shutil.copy(os.path.join(PROJECT_ROOT, "data", "cars.json"), data_dir)
        app = App(IOManager(), DataManager(data_dir=data_dir, project_dir=PROJECT_ROOT),
                  AIManager([], retry_delay=0), LogicManager())
        answers = iter(SESSION)
        monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
        app.run()
    finally:
        shutil.rmtree(data_dir)

    out = capsys.readouterr().out
    assert "Profile created" in out
    assert "1 service(s) added to your history" in out
    assert "NEEDS MANUAL REVIEW - AI assessment unavailable" in out
    assert "Profile updated." in out
    assert "Service updated:" in out
    assert "Service deleted." in out
    assert "Profile, history and checks deleted" in out
    assert out.rstrip().endswith("Goodbye!")
