"""Runs the repository contract against a REAL MongoDB server, to check the real
pymongo behaves like FakeCollection. Skipped unless MONGODB_TEST_URI is set: the CI
'mongodb' job starts a MongoDB container and sets it to mongodb://localhost:27017."""
import os

import pytest

from storage.mongo_connection import MongoConnection
from storage.mongo_repository import MongoRepository

URI = os.environ.get("MONGODB_TEST_URI")
pytestmark = pytest.mark.skipif(not URI, reason="MONGODB_TEST_URI is not set")


@pytest.fixture
def repository():
    connection = MongoConnection.connect(URI, "car_tracker_ci_test")
    assert connection is not None, "could not reach the test MongoDB server"
    collection = connection.collection("records")
    collection.delete_many({})                          # start each test empty
    yield MongoRepository(collection)
    collection.delete_many({})


def test_crud_on_a_real_server(repository):
    assert repository.insert({"plate": "SBA1234A", "km": 100})
    assert repository.insert({"plate": "SBA1234A", "km": 200})
    assert repository.insert({"plate": "SGX9999Z", "km": 50})
    assert [row["km"] for row in repository.find({"plate": "SBA1234A"})] == [100, 200]
    assert "_id" not in repository.find({})[0]          # Mongo's own id stays hidden

    assert repository.replace({"km": 200}, {"plate": "SBA1234A", "km": 250})
    assert not repository.replace({"km": 999}, {"plate": "X", "km": 1})
    assert repository.replace({"km": 999}, {"plate": "X", "km": 1}, upsert=True)
    assert repository.delete({"plate": "SBA1234A"}) == 2

    assert repository.save_all([{"plate": "A"}, {"plate": "B"}])
    assert repository.load_all() == [{"plate": "A"}, {"plate": "B"}]