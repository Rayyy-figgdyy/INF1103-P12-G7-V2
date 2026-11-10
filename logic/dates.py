"""
Static helpers for the app's saved DD-MM-YYYY dates.
"""
from __future__ import annotations

import datetime


class Dates:
    """Static helpers for the app's saved 'DD-MM-YYYY' dates. They need no object
    state, so they are @staticmethods grouped in one class (SRP: date handling only)."""

    DATE_FORMAT = "%d-%m-%Y"

    @staticmethod
    def to_date(value) -> datetime.date | None:
        """Turn saved text into real date.
        Returns None if the value is missing or not a valid date."""
        try:
            return datetime.datetime.strptime(str(value), Dates.DATE_FORMAT).date()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def to_date_any(value) -> datetime.date | None:
        """Accepts either a date object or saved 'DD-MM-YYYY' text; returns a date or None if
        date is not valid."""
        if isinstance(value, datetime.date):
            return value
        return Dates.to_date(value)

    @staticmethod
    def add_days(start: datetime.date, days: int) -> datetime.date:
        """Return the date `days` days after `start`."""
        return start + datetime.timedelta(days=days)

    @staticmethod
    def add_years(start: datetime.date, years: int) -> datetime.date:
        """Returns the same day `years` years later (29 Feb becomes 28 Feb if needed)."""
        try:
            return start.replace(year=start.year + years)
        except ValueError:                  # 29 Feb in a year that isn't a leap year
            return start.replace(year=start.year + years, day=28)
