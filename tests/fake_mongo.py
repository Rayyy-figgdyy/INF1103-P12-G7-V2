"""
Stand-ins for pymongo collections, so MongoRepository can be tested without a database.
FakeCollection keeps documents in a list and answers the same calls MongoRepository
makes; BrokenCollection fails every call, like a lost connection.
"""
import itertools
from types import SimpleNamespace

from pymongo.errors import PyMongoError


class FakeCursor:
    def __init__(self, documents, projection):
        self.documents = documents
        self.hidden = [field for field, show in (projection or {}).items() if not show]

    def sort(self, field, direction):
        self.documents.sort(key=lambda document: document[field], reverse=direction < 0)
        return self

    def __iter__(self):
        for document in self.documents:
            yield {key: value for key, value in document.items() if key not in self.hidden}


class FakeCollection:
    __ids = itertools.count(1)          # like MongoDB's _id: grows with every insert

    def __init__(self, name="records"):
        self.name = name
        self.documents = []

    @staticmethod
    def __matches(document, criteria):
        return all(document.get(field) == value for field, value in criteria.items())

    def find(self, criteria, projection=None):
        return FakeCursor([dict(d) for d in self.documents if self.__matches(d, criteria)],
                          projection)

    def insert_one(self, document):
        document["_id"] = next(self.__ids)          # MongoDB also adds _id to the dict
        self.documents.append(dict(document))
        return SimpleNamespace(inserted_id=document["_id"])

    def insert_many(self, documents):
        for document in documents:
            self.insert_one(document)

    def replace_one(self, criteria, replacement, upsert=False):
        for position, document in enumerate(self.documents):
            if self.__matches(document, criteria):
                self.documents[position] = {**replacement, "_id": document["_id"]}
                return SimpleNamespace(matched_count=1, upserted_id=None)
        if upsert:
            inserted = self.insert_one(replacement)
            return SimpleNamespace(matched_count=0, upserted_id=inserted.inserted_id)
        return SimpleNamespace(matched_count=0, upserted_id=None)

    def delete_many(self, criteria):
        before = len(self.documents)
        self.documents = [d for d in self.documents if not self.__matches(d, criteria)]
        return SimpleNamespace(deleted_count=before - len(self.documents))


class BrokenCollection:
    """Every call fails, as if the connection to MongoDB was lost."""
    name = "broken"

    def __getattr__(self, method):
        def fail(*args, **kwargs):
            raise PyMongoError("connection lost")
        return fail