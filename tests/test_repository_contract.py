"""
The Repository contract: every implementation must create, read, update and delete in
the same way, so any one can be swapped in (Liskov substitution). The same checks run
against each implementation listed in IMPLEMENTATIONS.
"""
import os
import tempfile

import pytest

from fake_mongo import FakeCollection
from storage.json_repository import JsonRepository
from storage.mongo_repository import MongoRepository


def json_file_repository():
    return JsonRepository(os.path.join(tempfile.mkdtemp(), "records.json"))


def mongo_repository():
    return MongoRepository(FakeCollection())


IMPLEMENTATIONS = [json_file_repository, mongo_repository]

OIL = {"license_plate": "SBA1234A", "part_name": "Engine Oil", "service_id": 1}
TYRES = {"license_plate": "SBA1234A", "part_name": "Tyres", "service_id": 2}
OTHER_CAR = {"license_plate": "SKX5555B", "part_name": "Engine Oil", "service_id": 3}


@pytest.fixture(params=IMPLEMENTATIONS, ids=lambda make: make.__name__)
def repository(request):
    return request.param()


def test_insert_then_find_by_criteria_in_saved_order(repository):
    for record in (OIL, TYRES, OTHER_CAR):
        assert repository.insert(record) is True
    assert repository.find({}) == [OIL, TYRES, OTHER_CAR]
    assert repository.find({"license_plate": "SBA1234A"}) == [OIL, TYRES]
    assert repository.find({"license_plate": "SBA1234A", "part_name": "Tyres"}) == [TYRES]
    assert repository.find({"license_plate": "NOPE"}) == []


def test_replace_updates_one_record_or_upserts(repository):
    repository.insert(OIL)
    changed = {**OIL, "part_name": "Coolant"}
    assert repository.replace({"service_id": 1}, changed) is True
    assert repository.find({}) == [changed]
    assert repository.replace({"service_id": 99}, TYRES) is False      # nothing matched
    assert repository.replace({"service_id": 2}, TYRES, upsert=True) is True
    assert repository.find({"service_id": 2}) == [TYRES]


def test_delete_returns_how_many_were_removed(repository):
    for record in (OIL, TYRES, OTHER_CAR):
        repository.insert(record)
    assert repository.delete({"license_plate": "SBA1234A"}) == 2
    assert repository.delete({"license_plate": "SBA1234A"}) == 0
    assert repository.find({}) == [OTHER_CAR]


def test_save_all_replaces_everything_and_load_all_reads_it(repository):
    repository.insert(OTHER_CAR)
    assert repository.save_all([OIL, TYRES]) is True
    assert repository.load_all() == [OIL, TYRES]