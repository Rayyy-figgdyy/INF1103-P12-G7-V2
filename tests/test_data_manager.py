"""
Tests for data_manager: user CRUD, maintenance history CRUD, prompt records, the stored
manufacturer schedule, repeat detection, and missing/corrupt file handling. Every test
that writes uses a temporary folder (DataManager(data_dir=tmp)), so real data in data/
is never touched. The last section tests the object-oriented design itself.
"""
import contextlib
import json
import logging
import os
import shutil
import tempfile

from data_manager import DataManager
from models.car import Car
from models.part_schedule import PartSchedule
from models.user_profile import UserProfile
from storage.car_catalogue import CarCatalogue
from storage.check_repository import CheckRepository
from storage.json_repository import JsonRepository
from storage.json_store import JsonStore
from storage.repository import Repository
from storage.service_history_repository import ServiceHistoryRepository
from storage.user_repository import UserRepository

USER = {
    "name": "Darren",
    "license_plate": "SBA1234A",
    "car_model": "Toyota Corolla 2020",
    "car_condition": "Used",
    "coe_expiry_date": "30-06-2030",
}


def profile(**changes) -> UserProfile:
    """USER as a UserProfile, with any fields changed."""
    return UserProfile.from_dict({**USER, **changes})


@contextlib.contextmanager
def temp_data_manager():
    """A DataManager whose data folder (and project folder) is an empty temp folder."""
    folder = tempfile.mkdtemp()
    try:
        yield DataManager(data_dir=folder, project_dir=folder)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def file_in(dm: DataManager, filename: str) -> str:
    return os.path.join(dm.data_dir, filename)


def write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# --- Missing / corrupt files ------------------------------------------------


def test_missing_files_return_empty():
    with temp_data_manager() as dm:
        assert dm.checks.load() == []
        assert dm.users.load_users() == []
        assert dm.users.find_by_plate("SBA1234A") is None


def test_corrupt_files_return_empty_instead_of_crashing():
    with temp_data_manager() as dm:
        write(file_in(dm, DataManager.CHECKS_FILENAME), "{this is not json")
        write(file_in(dm, DataManager.HISTORY_FILENAME), "[broken")
        write(file_in(dm, DataManager.USERS_FILENAME), '{"not": "a list"}')

        assert dm.checks.load() == []
        assert dm.history.load_all() == []
        assert dm.users.load_users() == []


# --- User CRUD ---------------------------------------------------------------


def test_create_and_read_user():
    with temp_data_manager() as dm:
        assert dm.users.save(profile()) is True
        assert dm.users.find_by_plate("SBA1234A").name == "Darren"


def test_update_replaces_instead_of_duplicating():
    with temp_data_manager() as dm:
        dm.users.save(profile())
        dm.users.save(profile(car_model="Honda Civic 2022"))

        users = dm.users.load_users()

        assert len(users) == 1
        assert users[0].car_model == "Honda Civic 2022"


def test_delete_user():
    with temp_data_manager() as dm:
        dm.users.save(profile())
        dm.users.save(profile(license_plate="SGX88B", name="Kai"))

        assert dm.users.delete("SBA1234A") is True
        assert dm.users.find_by_plate("SBA1234A") is None
        assert dm.users.find_by_plate("SGX88B") is not None
        assert dm.users.delete("SBA1234A") is False


# --- Maintenance records ----------------------------------------------------


def test_save_load_and_query_records():
    with temp_data_manager() as dm:
        dm.checks.save({"license_plate": "SBA1234A", "part_name": "Engine Oil",
                        "current_odometer": 40_000})
        dm.checks.save({"license_plate": "SGX88B", "part_name": "Battery",
                        "current_odometer": 9_000})

        assert len(dm.checks.load()) == 2

        mine = dm.checks.query(lambda r: r["license_plate"] == "SBA1234A")

        assert [r["part_name"] for r in mine] == ["Engine Oil"]
        assert dm.checks.for_plate("SBA1234A") == mine


def test_persists_across_separate_loads():
    with temp_data_manager() as dm:
        dm.checks.save({"license_plate": "SBA1234A", "current_odometer": 1})

        first = dm.checks.load()
        second = DataManager(data_dir=dm.data_dir).checks.load()   # a fresh object

        assert first == second == [{"license_plate": "SBA1234A", "current_odometer": 1}]


def test_last_odometer_is_per_car_across_all_parts():
    with temp_data_manager() as dm:
        dm.checks.save({"license_plate": "SBA1234A", "part_name": "Engine Oil",
                        "current_odometer": 40_000})
        dm.checks.save({"license_plate": "SBA1234A", "part_name": "Battery",
                        "current_odometer": 42_500})
        dm.checks.save({"license_plate": "SGX88B", "part_name": "Battery",
                        "current_odometer": 90_000})

        records = dm.checks.load()

        assert CheckRepository.last_odometer(records, "SBA1234A") == 42_500
        assert CheckRepository.last_odometer(records, "NEW1A") is None


def test_delete_records_for_plate():
    with temp_data_manager() as dm:
        dm.checks.save({"license_plate": "SBA1234A"})
        dm.checks.save({"license_plate": "SBA1234A"})
        dm.checks.save({"license_plate": "SGX88B"})

        assert dm.checks.delete_for_plate("SBA1234A") == 2
        assert dm.checks.load() == [{"license_plate": "SGX88B"}]


# --- Car catalogue -----------------------------------------------------------

CATALOGUE = {
    "cars": [
        {
            "model": "Honda Civic 2025",
            "condition": "Brand New",
            "manual": "manuals/honda.pdf",
            "schedule": {
                "Engine Oil": {"km": 10000, "months": 12},
                "Brake Pads": {"km": 40000, "months": 24},
            },
        },
        {
            "model": "Kia Forte",
            "condition": "Used",
            "manual": "manuals/kia.pdf",
            "schedule": {
                "Engine Oil": {"km": 8000, "months": 6},
            },
        },
    ]
}


def write_cars(dm: DataManager, catalogue) -> None:
    text = catalogue if isinstance(catalogue, str) else json.dumps(catalogue)
    write(file_in(dm, DataManager.CARS_FILENAME), text)


def test_lists_models_and_finds_condition():
    with temp_data_manager() as dm:
        write_cars(dm, CATALOGUE)

        assert dm.cars.list_models() == ["Honda Civic 2025", "Kia Forte"]
        assert dm.cars.find("Kia Forte").condition == "Used"
        assert dm.cars.find("Toyota Corolla") is None


def test_each_car_has_its_own_parts_and_intervals():
    with temp_data_manager() as dm:
        write_cars(dm, CATALOGUE)

        assert dm.cars.list_parts("Honda Civic 2025") == ["Brake Pads", "Engine Oil"]
        assert dm.cars.list_parts("Kia Forte") == ["Engine Oil"]
        assert dm.cars.get_service_interval("Kia Forte", "Engine Oil") == {
            "interval_km": 8000,
            "interval_months": 6,
            "action": "replace",
        }
        assert dm.cars.get_service_interval("Kia Forte", "Brake Pads") is None


def test_missing_or_corrupt_catalogue_returns_empty():
    with temp_data_manager() as dm:
        assert dm.cars.list_models() == []

        write_cars(dm, "garbage")

        assert dm.cars.list_models() == []
        assert dm.cars.list_parts("Kia Forte") == []


def test_invalid_entries_are_skipped():
    with temp_data_manager() as dm:
        bad = {
            "cars": [
                {"model": "Kia Forte", "condition": "Old", "manual": "x.pdf",
                 "schedule": {}},
                {"model": "Honda Civic 2025", "condition": "Brand New", "manual": "h.pdf",
                 "schedule": {
                     "Engine Oil": {"km": 10000, "months": 12},
                     "Tyres": {"km": "lots"},
                 }},
            ]
        }
        write_cars(dm, bad)

        assert dm.cars.list_models() == ["Honda Civic 2025"]
        assert dm.cars.list_parts("Honda Civic 2025") == ["Engine Oil"]


def test_manual_path_only_when_file_exists():
    data_folder = tempfile.mkdtemp()
    project_folder = tempfile.mkdtemp()
    try:
        cars_path = os.path.join(data_folder, "cars.json")
        write(cars_path, json.dumps(CATALOGUE))

        # Project folder without the manual: not found.
        catalogue = CarCatalogue(JsonStore(cars_path), project_dir=data_folder)
        assert catalogue.get_manual_path("Kia Forte") is None

        # Project folder that has manuals/kia.pdf: found.
        os.makedirs(os.path.join(project_folder, "manuals"))
        write(os.path.join(project_folder, "manuals", "kia.pdf"), "%PDF-1.4")
        catalogue = CarCatalogue(JsonStore(cars_path), project_dir=project_folder)
        assert catalogue.get_manual_path("Kia Forte").endswith("manuals/kia.pdf")
    finally:
        shutil.rmtree(data_folder, ignore_errors=True)
        shutil.rmtree(project_folder, ignore_errors=True)


def test_real_catalogue_file_is_valid():
    cars = DataManager().cars      # the real data/cars.json, read only

    assert cars.list_models() == [
        "Honda City 2025",
        "Mazda 3 Hatchback 2020",
        "Hyundai Elantra 2021",
        "Kia Forte 2024",
    ]
    for model in cars.list_models():
        assert len(cars.list_parts(model)) >= 1, model


def test_last_odometer_skips_damaged_entries():
    records = [
        {"license_plate": "SBA1234A", "current_odometer": 40_000},
        {"license_plate": "SBA1234A", "current_odometer": "52000"},
        {"license_plate": "SBA1234A"},
    ]

    assert CheckRepository.last_odometer(records, "SBA1234A") == 40_000


# --- Repeated checks are detected -------------------------------------------

CHECK = {
    "license_plate": "SBA1234A",
    "part_name": "Engine Oil",
    "last_service_date": "03-09-2025",
    "last_service_mileage": 40_000,
    "current_odometer": 49_000,
    "check_date": "01-10-2026",
    "interval_km": 10_000,
    "interval_months": 12,
    "action": "replace",
    "interval_stage": "first",
}


def test_identical_check_is_found_as_repeat():
    with temp_data_manager() as dm:
        dm.checks.save({**CHECK, "urgency_score": 3})

        previous = dm.checks.find_repeat(CHECK)

        assert previous is not None
        assert previous["urgency_score"] == 3


def test_different_check_date_is_not_a_repeat():
    with temp_data_manager() as dm:
        dm.checks.save({**CHECK, "urgency_score": 3})

        previous = dm.checks.find_repeat({**CHECK, "check_date": "09-10-2026"})

        assert previous is None


def test_any_changed_repeat_field_is_not_a_repeat():
    with temp_data_manager() as dm:
        dm.checks.save({**CHECK, "urgency_score": 3})

        changed_inputs = [
            ("license_plate", "SGX88B"),
            ("part_name", "Coolant"),
            ("last_service_date", "04-09-2025"),
            ("last_service_mileage", 40_001),
            ("current_odometer", 49_500),
            ("check_date", "09-10-2026"),
            ("interval_km", 20_000),
            ("interval_months", 24),
            ("action", "inspect"),
            ("interval_stage", "repeat"),
        ]
        for field, new_value in changed_inputs:
            changed_check = {**CHECK, field: new_value}
            assert dm.checks.find_repeat(changed_check) is None, field


# --- Maintenance history CRUD -----------------------------------------------

SERVICE = {
    "license_plate": "SBA1234A",
    "part_name": "Engine Oil",
    "service_date": "20-03-2026",
    "service_odometer": 58_000,
    "notes": "Ah Seng Motors",
}


def test_add_service_gives_each_entry_its_own_id():
    with temp_data_manager() as dm:
        first = dm.history.add(SERVICE)
        second = dm.history.add({**SERVICE, "part_name": "Coolant"})

        assert first["service_id"] == 1
        assert second["service_id"] == 2
        assert len(dm.history.for_plate("SBA1234A")) == 2
        assert dm.history.for_plate("SGX88B") == []


def test_update_service_replaces_the_entry():
    with temp_data_manager() as dm:
        saved = dm.history.add(SERVICE)

        assert dm.history.update({**saved, "service_odometer": 58_500}) is True

        [entry] = dm.history.for_plate("SBA1234A")

        assert entry["service_odometer"] == 58_500


def test_update_or_delete_unknown_service_fails():
    with temp_data_manager() as dm:
        dm.history.add(SERVICE)

        assert dm.history.update({**SERVICE, "service_id": 99}) is False
        assert dm.history.delete(99) is False


def test_delete_service_and_delete_history_for_plate():
    with temp_data_manager() as dm:
        first = dm.history.add(SERVICE)
        dm.history.add({**SERVICE, "part_name": "Coolant"})
        dm.history.add({**SERVICE, "license_plate": "SGX88B"})

        assert dm.history.delete(first["service_id"]) is True
        assert len(dm.history.for_plate("SBA1234A")) == 1
        assert dm.history.delete_for_plate("SBA1234A") == 1
        assert len(dm.history.load_all()) == 1


def test_last_odometer_counts_service_entries_too():
    saved = [
        {"license_plate": "SBA1234A", "current_odometer": 60_000},
        {"license_plate": "SBA1234A", "service_odometer": 61_000},
    ]

    assert CheckRepository.last_odometer(saved, "SBA1234A") == 61_000


# --- Model year --------------------------------------------------------------


def test_model_year_from_cars_json_or_model_name():
    with temp_data_manager() as dm:
        cars = {
            "cars": [
                {"model": "Kia Forte", "condition": "Used", "year": 2024, "manual": "m.pdf",
                 "schedule": {"Engine Oil": {"km": 10000, "months": 12}}},
                {"model": "Mazda 3 Hatchback 2020", "condition": "Used", "manual": "m.pdf",
                 "schedule": {"Engine Oil": {"km": 10000, "months": 12}}},
            ]
        }
        write_cars(dm, cars)

        assert dm.cars.get_model_year("Kia Forte") == 2024
        assert dm.cars.get_model_year("Mazda 3 Hatchback 2020") == 2020
        assert dm.cars.get_model_year("Unknown Car") is None


def test_interval_may_have_no_km_or_no_time_limit_but_not_neither():
    # The schedule-line check now lives on PartSchedule (models.py).
    assert PartSchedule.is_valid_entry({"km": 100000, "months": 0}) is True
    assert PartSchedule.is_valid_entry({"km": 0, "months": 12}) is True
    assert PartSchedule.is_valid_entry({"km": 0, "months": 0}) is False
    assert PartSchedule.is_valid_entry({"km": -5, "months": 12}) is False
    assert PartSchedule.is_valid_entry({"km": True, "months": 12}) is False


def test_schedule_entries_with_action_and_first_then_repeat_rule():
    assert PartSchedule.is_valid_entry({"action": "inspect", "km": 15000,
                                        "months": 12}) is True
    assert PartSchedule.is_valid_entry({"action": "polish", "km": 15000,
                                        "months": 12}) is False

    coolant = {
        "action": "replace",
        "km": 200000,
        "months": 120,
        "repeat_km": 40000,
        "repeat_months": 24,
    }
    assert PartSchedule.is_valid_entry(coolant) is True
    assert PartSchedule.is_valid_entry({**coolant, "repeat_months": "two years"}) is False


def test_real_cars_json_is_valid_and_complete():
    cars = DataManager().cars      # the real data/cars.json, read only

    for model in cars.list_models():
        assert cars.list_parts(model) == [
            "Brake Pads",
            "Coolant",
            "Engine Air Filter",
            "Engine Oil",
            "Spark Plugs",
            "Tyres",
        ], model
        assert cars.get_service_interval(model, "Coolant")["repeat_km"] > 0, model
        assert cars.get_service_interval(model, "Brake Pads")["action"] == "inspect", model
        assert cars.get_service_interval(model, "Tyres")["action"] == "rotate", model

    assert len(cars.list_models()) == 4


# --- Manufacturer schedule validation ---------------------------------------


def test_manufacturer_schedules_match_reference():
    schedules = {
        "Honda City 2025": {
            "Engine Oil": (10000, 12, "replace"), "Brake Pads": (10000, 12, "inspect"),
            "Spark Plugs": (100000, 0, "replace"), "Tyres": (10000, 0, "rotate"),
            "Engine Air Filter": (30000, 0, "replace"),
            "Coolant": (200000, 120, "replace", 100000, 60),
        },
        "Mazda 3 Hatchback 2020": {
            "Engine Oil": (16000, 12, "replace"), "Brake Pads": (16000, 12, "inspect"),
            "Spark Plugs": (120000, 0, "replace"), "Tyres": (16000, 0, "rotate"),
            "Engine Air Filter": (48000, 36, "replace"),
            "Coolant": (192000, 120, "replace", 96000, 60),
        },
        "Hyundai Elantra 2021": {
            "Engine Oil": (15000, 12, "replace"), "Brake Pads": (15000, 12, "inspect"),
            "Spark Plugs": (160000, 0, "replace"), "Tyres": (12000, 0, "rotate"),
            "Engine Air Filter": (45000, 36, "replace"),
            "Coolant": (200000, 120, "replace", 40000, 24),
        },
        "Kia Forte 2024": {
            "Engine Oil": (13000, 12, "replace"), "Brake Pads": (13000, 12, "inspect"),
            "Spark Plugs": (156000, 0, "replace"), "Tyres": (13000, 12, "rotate"),
            "Engine Air Filter": (39000, 36, "replace"),
            "Coolant": (195000, 120, "replace", 39000, 24),
        },
    }
    cars = DataManager().cars      # the real data/cars.json, read only
    for model, parts in schedules.items():
        for part, expected in parts.items():
            rule = cars.get_service_interval(model, part)
            assert (rule["interval_km"], rule["interval_months"], rule["action"]) == expected[:3]
            if part == "Coolant":
                assert (rule["repeat_km"], rule["repeat_months"]) == expected[3:]


def test_history_for_part_returns_only_matching_part():
    with temp_data_manager() as dm:
        dm.history.add({**SERVICE, "part_name": "Brake Pads"})
        dm.history.add({**SERVICE, "part_name": "Engine Oil"})
        result = dm.history.for_part("SBA1234A", "Brake Pads")
        assert len(result) == 1 and result[0]["part_name"] == "Brake Pads"


def test_brake_history_change_prevents_repeat_reuse():
    history = [
        {"service_date": "01-01-2022", "service_odometer": 20000, "service_action": "replace"},
        {"service_date": "01-01-2024", "service_odometer": 40000, "service_action": "replace"},
        {"service_date": "01-01-2026", "service_odometer": 60000, "service_action": "replace"},
    ]
    first = {**CHECK, "part_name": "Brake Pads", "brake_pad_history": history,
             "history_context": {"eligible": True, "replacement_count": 3, "reason": ""}}
    changed = {**first, "brake_pad_history": [dict(item) for item in history]}
    changed["brake_pad_history"][2]["service_odometer"] = 61000
    with temp_data_manager() as dm:
        dm.checks.save({**first, "urgency_score": 6})
        assert dm.checks.find_repeat(first) is not None
        assert dm.checks.find_repeat(changed) is None


# --- Object-oriented design --------------------------------------------------


class InMemoryRepository(Repository):
    """A Repository that keeps records in a Python list instead of a file."""

    def __init__(self):
        self.items = []

    def load_all(self) -> list[dict]:
        return list(self.items)

    def save_all(self, items: list[dict]) -> bool:
        self.items = list(items)
        return True


def test_any_repository_can_be_used_by_user_repository():
    # Interface + Liskov substitution: UserRepository only needs load_all/save_all,
    # so an in-memory Repository works exactly like the JSON one.
    memory = InMemoryRepository()
    users = UserRepository(memory)

    assert users.save(profile()) is True
    assert users.save(profile(car_model="Honda Civic 2022")) is True
    assert memory.items == [{**USER, "car_model": "Honda Civic 2022"}]
    assert users.find_by_plate("SBA1234A").car_model == "Honda Civic 2022"
    assert users.delete("SBA1234A") is True and memory.items == []

    history = ServiceHistoryRepository(InMemoryRepository())
    assert history.add(SERVICE)["service_id"] == 1


def test_repository_interface_cannot_be_instantiated():
    try:
        Repository()
    except TypeError:
        pass
    else:
        raise AssertionError("Repository is abstract and must not be created directly")
    assert isinstance(JsonRepository("unused.json"), Repository)


def test_users_json_keeps_the_original_format():
    # UserProfile.to_dict / from_dict round-trip: the file holds the same plain dicts.
    with temp_data_manager() as dm:
        dm.users.save(profile())
        with open(file_in(dm, DataManager.USERS_FILENAME), encoding="utf-8") as f:
            assert json.load(f) == [USER]

        loaded = dm.users.find_by_plate("SBA1234A")
        assert isinstance(loaded, UserProfile)
        assert loaded.to_dict() == USER
        assert UserProfile.from_dict(loaded.to_dict()).to_dict() == USER


def test_catalogue_returns_cars_composed_of_part_schedules():
    with temp_data_manager() as dm:
        write_cars(dm, CATALOGUE)
        car = dm.cars.find("Kia Forte")

        assert isinstance(car, Car)
        schedule = car.schedule_for("Engine Oil")
        assert isinstance(schedule, PartSchedule)
        assert schedule.as_rule() == dm.cars.get_service_interval("Kia Forte", "Engine Oil")


def test_invalid_car_is_logged_with_the_original_message():
    records = []

    class ListHandler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = ListHandler()
    logging.getLogger("data_manager").addHandler(handler)
    try:
        with temp_data_manager() as dm:
            bad_car = {"model": "Kia Forte", "condition": "Old", "manual": "x.pdf",
                       "schedule": {}}
            write_cars(dm, {"cars": [bad_car]})
            assert dm.cars.load_cars() == []
            path = file_in(dm, DataManager.CARS_FILENAME)
            assert records == [f"Skipping invalid car entry in {path}: {bad_car!r}"]
    finally:
        logging.getLogger("data_manager").removeHandler(handler)


def test_data_manager_composes_its_parts_and_combines_odometers():
    with temp_data_manager() as dm:
        assert isinstance(dm.users, UserRepository)
        assert isinstance(dm.history, ServiceHistoryRepository)
        assert isinstance(dm.checks, CheckRepository)
        assert isinstance(dm.cars, CarCatalogue)

        dm.checks.save({"license_plate": "SBA1234A", "current_odometer": 60_000})
        dm.history.add({**SERVICE, "service_odometer": 61_000})
        assert dm.last_odometer_on_file("SBA1234A") == 61_000
        assert dm.last_odometer_on_file("SGX88B") is None
