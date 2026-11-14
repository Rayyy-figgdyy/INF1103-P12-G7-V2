"""
<<abstract>> ListRepository: a Repository whose records are kept as one list that is
read and written whole, such as a JSON file. It builds the create/read/update/delete
operations from load_all() and save_all(), so each subclass only implements those two.
"""
from __future__ import annotations

from abc import ABC

from storage.repository import Repository


class ListRepository(Repository, ABC):
    """ABSTRACT CLASS with shared behaviour: find/insert/replace/delete are written once
    here (INHERITANCE); load_all and save_all are left to the subclass. Damaged
    entries (not dicts) are never matched, and are kept as they are."""

    def find(self, criteria: dict) -> list[dict]:
        return [record for record in self.load_all() if self.__matches(record, criteria)]

    def insert(self, record: dict) -> bool:
        records = self.load_all()
        records.append(dict(record))
        return self.save_all(records)

    def replace(self, criteria: dict, record: dict, upsert: bool = False) -> bool:
        records = self.load_all()
        for position, existing in enumerate(records):
            if self.__matches(existing, criteria):
                records[position] = dict(record)
                return self.save_all(records)
        if not upsert:
            return False
        records.append(dict(record))
        return self.save_all(records)

    def delete(self, criteria: dict) -> int:
        records = self.load_all()
        remaining = [record for record in records if not self.__matches(record, criteria)]
        removed = len(records) - len(remaining)
        if removed and not self.save_all(remaining):
            return 0                    # the write failed, so nothing was really deleted
        return removed

    @staticmethod
    def __matches(record, criteria: dict) -> bool:
        """True if record is a dict whose fields equal every value in criteria."""
        return isinstance(record, dict) and all(
            record.get(field) == value for field, value in criteria.items())