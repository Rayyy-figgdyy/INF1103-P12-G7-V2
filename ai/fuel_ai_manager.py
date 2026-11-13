# The fuel feature uses the same Gemini and Groq objects as Part 1.
# This class only adds one fuel-analysis method to the existing AI Manager.
from __future__ import annotations

from ai_manager import AIManager
from ai.fuel_ai_advisor import FuelAIAdvisor


class FuelAIManager(AIManager):
    # Ask the providers about the calculated fuel readings.
    # Python has already calculated the km/L values.
    def analyse_fuel(self, dashboard: dict, car_model: str = "") -> dict:
        return FuelAIAdvisor(self.providers).analyse(dashboard, car_model)
