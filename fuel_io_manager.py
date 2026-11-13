# Fuel menus and terminal input/output are inherited from IOManager.
from __future__ import annotations

from io_manager import IOManager


class FuelIOManager(IOManager):
    # Group the fuel feature separately and move Exit to option 12.
    MENU_LOGGED_IN = IOManager.MENU_LOGGED_IN.replace(
        "11) Exit",
        "--- Fuel Tracker ---\n11) Fuel Consumption & AI Analysis\n12) Exit"
    )
