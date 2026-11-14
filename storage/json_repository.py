"""
A Repository kept in one JSON file. INHERITANCE: a ListRepository, so it only needs
load_all and save_all. COMPOSES (creates and owns) its JsonStore.
"""
from __future__ import annotations

from storage.json_store import JsonStore
from storage.list_repository import ListRepository


class JsonRepository(ListRepository):
    """A Repository kept in one JSON file. COMPOSITION: it creates and owns its
    JsonStore, which has no life outside this repository."""

    def __init__(self, path: str):
        self.__store = JsonStore(path)

    @property
    def path(self) -> str:
        return self.__store.path

    def load_all(self) -> list[dict]:
        return self.__store.read_list()

    def save_all(self, items: list[dict]) -> bool:
        return self.__store.write_list(items)
