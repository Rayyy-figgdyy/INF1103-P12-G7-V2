"""JsonToMongoImporter: copies the JSON files into MongoDB once, without duplicating
records if it is run again. A fake database is used, so no network is needed."""
import os
import tempfile

from fake_mongo import FakeCollection
from storage.json_repository import JsonRepository
from storage.json_to_mongo_importer import JsonToMongoImporter
from storage.repository_factory import RepositoryFactory


class FakeConnection:
    """Stands in for MongoConnection: one FakeCollection per name, no network."""

    def __init__(self):
        self.collections = {}

    @property
    def database_name(self) -> str:
        return "test_db"

    def collection(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection(name))


def test_importer_copies_the_json_files_once():
    connection = FakeConnection()
    with tempfile.TemporaryDirectory() as data_dir:
        JsonRepository(os.path.join(data_dir, "users.json")).save_all([{"name": "Darren"}])
        importer = JsonToMongoImporter(RepositoryFactory(connection), data_dir)
        assert importer.run() == 1
        assert importer.run() == 0                       # already there: skipped
        assert importer.run(overwrite=True) == 1         # replaced, not duplicated
    assert connection.collections["users"].documents[0]["name"] == "Darren"
    assert len(connection.collections["users"].documents) == 1