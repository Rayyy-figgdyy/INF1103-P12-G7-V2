"""
Tests for data_manager: user CRUD, maintenance history CRUD, prompt records, the stored
manufacturer schedule, repeat detection, and missing/corrupt file handling. Every test
uses a temporary folder, so real data in data/ is never touched.
"""
import contextlib
import json
import os
import shutil
import tempfile

import data_manager

USER = {
    "name": "Darren",
    "license_plate": "SBA1234A",
    "car_model": "Toyota Corolla 2020",
    "car_condition": "Used",
    "coe_expiry_date": "30-06-2030",
}


@contextlib.contextmanager
def temp_data_files():
    """Point data_manager at empty temp files for the duration of a test."""
    saved = (
        data_manager.PROMPTS_FILE,
        data_manager.HISTORY_FILE,
        data_manager.USERS_FILE,
        data_manager.CARS_FILE,
    )

    folder = tempfile.mkdtemp()

    data_manager.PROMPTS_FILE = os.path.join(folder, "prompt_records.json")
    data_manager.HISTORY_FILE = os.path.join(folder, "maintenance_history.json")
    data_manager.USERS_FILE = os.path.join(folder, "users.json")
    data_manager.CARS_FILE = os.path.join(folder, "cars.json")

    try:
        yield folder
    finally:
        (
            data_manager.PROMPTS_FILE,
            data_manager.HISTORY_FILE,
            data_manager.USERS_FILE,
            data_manager.CARS_FILE,
        ) = saved

        shutil.rmtree(folder, ignore_errors=True)


def write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# --- Missing / corrupt files ------------------------------------------------


def test_missing_files_return_empty():
    with temp_data_files():
        assert data_manager.load() == []
        assert data_manager.load_users() == []
        assert data_manager.find_user_by_plate("SBA1234A") is None


def test_corrupt_files_return_empty_instead_of_crashing():
    with temp_data_files():
        write(data_manager.PROMPTS_FILE, "{this is not json")
        write(data_manager.HISTORY_FILE, "[broken")
        write(data_manager.USERS_FILE, '{"not": "a list"}')

        assert data_manager.load() == []
        assert data_manager.load_history() == []
        assert data_manager.load_users() == []


# --- User CRUD ---------------------------------------------------------------


def test_create_and_read_user():
    with temp_data_files():
        assert data_manager.save_user(USER) is True
        assert data_manager.find_user_by_plate("SBA1234A")["name"] == "Darren"


def test_update_replaces_instead_of_duplicating():
    with temp_data_files():
        data_manager.save_user(USER)

        data_manager.save_user({
            **USER,
            "car_model": "Honda Civic 2022",
        })

        users = data_manager.load_users()

        assert len(users) == 1
        assert users[0]["car_model"] == "Honda Civic 2022"


def test_delete_user():
    with temp_data_files():
        data_manager.save_user(USER)

        data_manager.save_user({
            **USER,
            "license_plate": "SGX88B",
            "name": "Kai",
        })

        assert data_manager.delete_user("SBA1234A") is True
        assert data_manager.find_user_by_plate("SBA1234A") is None
        assert data_manager.find_user_by_plate("SGX88B") is not None
        assert data_manager.delete_user("SBA1234A") is False


# --- Maintenance records ----------------------------------------------------


def test_save_load_and_query_records():
    with temp_data_files():
        data_manager.save({
            "license_plate": "SBA1234A",
            "part_name": "Engine Oil",
            "current_odometer": 40_000,
        })

        data_manager.save({
            "license_plate": "SGX88B",
            "part_name": "Battery",
            "current_odometer": 9_000,
        })

        assert len(data_manager.load()) == 2

        mine = data_manager.query(
            lambda r: r["license_plate"] == "SBA1234A"
        )

        assert [r["part_name"] for r in mine] == ["Engine Oil"]


def test_persists_across_separate_loads():
    with temp_data_files():
        data_manager.save({
            "license_plate": "SBA1234A",
            "current_odometer": 1,
        })

        first = data_manager.load()
        second = data_manager.load()

        assert first == second == [
            {
                "license_plate": "SBA1234A",
                "current_odometer": 1,
            }
        ]


def test_last_odometer_is_per_car_across_all_parts():
    with temp_data_files():
        data_manager.save({
            "license_plate": "SBA1234A",
            "part_name": "Engine Oil",
            "current_odometer": 40_000,
        })

        data_manager.save({
            "license_plate": "SBA1234A",
            "part_name": "Battery",
            "current_odometer": 42_500,
        })

        data_manager.save({
            "license_plate": "SGX88B",
            "part_name": "Battery",
            "current_odometer": 90_000,
        })

        records = data_manager.load()

        assert data_manager.get_last_odometer(
            records,
            "SBA1234A",
        ) == 42_500

        assert data_manager.get_last_odometer(
            records,
            "NEW1A",
        ) is None


def test_delete_records_for_plate():
    with temp_data_files():
        data_manager.save({
            "license_plate": "SBA1234A",
        })

        data_manager.save({
            "license_plate": "SBA1234A",
        })

        data_manager.save({
            "license_plate": "SGX88B",
        })

        assert data_manager.delete_records_for_plate(
            "SBA1234A"
        ) == 2

        assert data_manager.load() == [
            {
                "license_plate": "SGX88B",
            }
        ]


# --- Car catalogue -----------------------------------------------------------

CATALOGUE = {
    "cars": [
        {
            "model": "Honda Civic 2025",
            "condition": "Brand New",
            "manual": "manuals/honda.pdf",
            "schedule": {
                "Engine Oil": {
                    "km": 10000,
                    "months": 12,
                },
                "Brake Pads": {
                    "km": 40000,
                    "months": 24,
                },
            },
        },
        {
            "model": "Kia Forte",
            "condition": "Used",
            "manual": "manuals/kia.pdf",
            "schedule": {
                "Engine Oil": {
                    "km": 8000,
                    "months": 6,
                }
            },
        },
    ]
}


def test_lists_models_and_finds_condition():
    with temp_data_files():
        write(
            data_manager.CARS_FILE,
            json.dumps(CATALOGUE),
        )

        assert data_manager.list_car_models() == [
            "Honda Civic 2025",
            "Kia Forte",
        ]

        assert data_manager.find_car(
            "Kia Forte"
        )["condition"] == "Used"

        assert data_manager.find_car(
            "Toyota Corolla"
        ) is None


def test_each_car_has_its_own_parts_and_intervals():
    with temp_data_files():
        write(
            data_manager.CARS_FILE,
            json.dumps(CATALOGUE),
        )

        assert data_manager.list_parts(
            "Honda Civic 2025"
        ) == [
            "Brake Pads",
            "Engine Oil",
        ]

        assert data_manager.list_parts(
            "Kia Forte"
        ) == [
            "Engine Oil"
        ]

        assert data_manager.get_service_interval(
            "Kia Forte",
            "Engine Oil",
        ) == {
            "interval_km": 8000,
            "interval_months": 6,
            "action": "replace",
        }

        assert data_manager.get_service_interval(
            "Kia Forte",
            "Brake Pads",
        ) is None


def test_missing_or_corrupt_catalogue_returns_empty():
    with temp_data_files():
        assert data_manager.list_car_models() == []

        write(
            data_manager.CARS_FILE,
            "garbage",
        )

        assert data_manager.list_car_models() == []
        assert data_manager.list_parts("Kia Forte") == []


def test_invalid_entries_are_skipped():
    with temp_data_files():
        bad = {
            "cars": [
                {
                    "model": "Kia Forte",
                    "condition": "Old",
                    "manual": "x.pdf",
                    "schedule": {},
                },
                {
                    "model": "Honda Civic 2025",
                    "condition": "Brand New",
                    "manual": "h.pdf",
                    "schedule": {
                        "Engine Oil": {
                            "km": 10000,
                            "months": 12,
                        },
                        "Tyres": {
                            "km": "lots",
                        },
                    },
                },
            ]
        }

        write(
            data_manager.CARS_FILE,
            json.dumps(bad),
        )

        assert data_manager.list_car_models() == [
            "Honda Civic 2025"
        ]

        assert data_manager.list_parts(
            "Honda Civic 2025"
        ) == [
            "Engine Oil"
        ]


def test_manual_path_only_when_file_exists():
    with temp_data_files():
        write(
            data_manager.CARS_FILE,
            json.dumps(CATALOGUE),
        )

        assert data_manager.get_manual_path(
            "Kia Forte"
        ) is None

        saved = data_manager.PROJECT_DIR
        data_manager.PROJECT_DIR = tempfile.mkdtemp()

        try:
            os.makedirs(
                os.path.join(
                    data_manager.PROJECT_DIR,
                    "manuals",
                )
            )

            write(
                os.path.join(
                    data_manager.PROJECT_DIR,
                    "manuals",
                    "kia.pdf",
                ),
                "%PDF-1.4",
            )

            assert data_manager.get_manual_path(
                "Kia Forte"
            ).endswith(
                "manuals/kia.pdf"
            )

        finally:
            shutil.rmtree(
                data_manager.PROJECT_DIR,
                ignore_errors=True,
            )

            data_manager.PROJECT_DIR = saved


def test_real_catalogue_file_is_valid():
    assert data_manager.list_car_models() == [
        "Honda City 2025",
        "Mazda 3 Hatchback 2020",
        "Hyundai Elantra 2021",
        "Kia Forte",
    ]

    for model in data_manager.list_car_models():
        assert len(
            data_manager.list_parts(model)
        ) >= 1, model


def test_last_odometer_skips_damaged_entries():
    records = [
        {
            "license_plate": "SBA1234A",
            "current_odometer": 40_000,
        },
        {
            "license_plate": "SBA1234A",
            "current_odometer": "52000",
        },
        {
            "license_plate": "SBA1234A",
        },
    ]

    assert data_manager.get_last_odometer(
        records,
        "SBA1234A",
    ) == 40_000


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
    with temp_data_files():
        data_manager.save({
            **CHECK,
            "urgency_score": 3,
        })

        previous = data_manager.find_repeat(
            CHECK
        )

        assert previous is not None
        assert previous["urgency_score"] == 3


def test_different_check_date_is_not_a_repeat():
    with temp_data_files():
        data_manager.save({
            **CHECK,
            "urgency_score": 3,
        })

        previous = data_manager.find_repeat({
            **CHECK,
            "check_date": "09-10-2026",
        })

        assert previous is None


def test_any_changed_repeat_field_is_not_a_repeat():
    with temp_data_files():
        data_manager.save({
            **CHECK,
            "urgency_score": 3,
        })

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
            changed_check = {
                **CHECK,
                field: new_value,
            }

            assert data_manager.find_repeat(
                changed_check
            ) is None, field


def test_no_history_means_no_repeat():
    with temp_data_files():
        assert data_manager.find_repeat(
            CHECK
        ) is None


# --- Maintenance history CRUD -----------------------------------------------

SERVICE = {
    "license_plate": "SBA1234A",
    "part_name": "Engine Oil",
    "service_date": "20-03-2026",
    "service_odometer": 58_000,
    "notes": "Ah Seng Motors",
}


def test_add_service_gives_each_entry_its_own_id():
    with temp_data_files():
        first = data_manager.add_service(
            SERVICE
        )

        second = data_manager.add_service({
            **SERVICE,
            "part_name": "Coolant",
        })

        assert first["service_id"] == 1
        assert second["service_id"] == 2

        assert len(
            data_manager.history_for_plate(
                "SBA1234A"
            )
        ) == 2

        assert data_manager.history_for_plate(
            "SGX88B"
        ) == []


def test_update_service_replaces_the_entry():
    with temp_data_files():
        saved = data_manager.add_service(
            SERVICE
        )

        assert data_manager.update_service({
            **saved,
            "service_odometer": 58_500,
        }) is True

        [entry] = data_manager.history_for_plate(
            "SBA1234A"
        )

        assert entry["service_odometer"] == 58_500


def test_update_or_delete_unknown_service_fails():
    with temp_data_files():
        data_manager.add_service(
            SERVICE
        )

        assert data_manager.update_service({
            **SERVICE,
            "service_id": 99,
        }) is False

        assert data_manager.delete_service(
            99
        ) is False


def test_delete_service_and_delete_history_for_plate():
    with temp_data_files():
        first = data_manager.add_service(
            SERVICE
        )

        data_manager.add_service({
            **SERVICE,
            "part_name": "Coolant",
        })

        data_manager.add_service({
            **SERVICE,
            "license_plate": "SGX88B",
        })

        assert data_manager.delete_service(
            first["service_id"]
        ) is True

        assert len(
            data_manager.history_for_plate(
                "SBA1234A"
            )
        ) == 1

        assert data_manager.delete_history_for_plate(
            "SBA1234A"
        ) == 1

        assert len(
            data_manager.load_history()
        ) == 1


def test_last_odometer_counts_service_entries_too():
    saved = [
        {
            "license_plate": "SBA1234A",
            "current_odometer": 60_000,
        },
        {
            "license_plate": "SBA1234A",
            "service_odometer": 61_000,
        },
    ]

    assert data_manager.get_last_odometer(
        saved,
        "SBA1234A",
    ) == 61_000


# --- Model year --------------------------------------------------------------


def test_model_year_from_cars_json_or_model_name():
    with temp_data_files():
        cars = {
            "cars": [
                {
                    "model": "Kia Forte",
                    "condition": "Used",
                    "year": 2024,
                    "manual": "m.pdf",
                    "schedule": {
                        "Engine Oil": {
                            "km": 10000,
                            "months": 12,
                        }
                    },
                },
                {
                    "model": "Mazda 3 Hatchback 2020",
                    "condition": "Used",
                    "manual": "m.pdf",
                    "schedule": {
                        "Engine Oil": {
                            "km": 10000,
                            "months": 12,
                        }
                    },
                },
            ]
        }

        write(
            data_manager.CARS_FILE,
            json.dumps(cars),
        )

        assert data_manager.get_model_year(
            "Kia Forte"
        ) == 2024

        assert data_manager.get_model_year(
            "Mazda 3 Hatchback 2020"
        ) == 2020

        assert data_manager.get_model_year(
            "Unknown Car"
        ) is None


def test_interval_may_have_no_km_or_no_time_limit_but_not_neither():
    assert data_manager.is_valid_interval({
        "km": 100000,
        "months": 0,
    }) is True

    assert data_manager.is_valid_interval({
        "km": 0,
        "months": 12,
    }) is True

    assert data_manager.is_valid_interval({
        "km": 0,
        "months": 0,
    }) is False

    assert data_manager.is_valid_interval({
        "km": -5,
        "months": 12,
    }) is False

    assert data_manager.is_valid_interval({
        "km": True,
        "months": 12,
    }) is False


def test_schedule_entries_with_action_and_first_then_repeat_rule():
    assert data_manager.is_valid_interval({
        "action": "inspect",
        "km": 15000,
        "months": 12,
    }) is True

    assert data_manager.is_valid_interval({
        "action": "polish",
        "km": 15000,
        "months": 12,
    }) is False

    coolant = {
        "action": "replace",
        "km": 200000,
        "months": 120,
        "repeat_km": 40000,
        "repeat_months": 24,
    }

    assert data_manager.is_valid_interval(
        coolant
    ) is True

    assert data_manager.is_valid_interval({
        **coolant,
        "repeat_months": "two years",
    }) is False


def test_real_cars_json_is_valid_and_complete():
    for model in data_manager.list_car_models():
        parts = data_manager.list_parts(model)

        assert parts == [
            "Brake Pads",
            "Coolant",
            "Engine Air Filter",
            "Engine Oil",
            "Spark Plugs",
            "Tyres",
        ], model

        assert data_manager.get_service_interval(
            model,
            "Coolant",
        )["repeat_km"] > 0, model

        assert data_manager.get_service_interval(
            model,
            "Brake Pads",
        )["action"] == "inspect", model

        assert data_manager.get_service_interval(
            model,
            "Tyres",
        )["action"] == "rotate", model

    assert len(
        data_manager.list_car_models()
    ) == 4


# --- Manufacturer schedule validation ---------------------------------------


def test_honda_city_manufacturer_schedule():
    assert data_manager.get_service_interval(
        "Honda City 2025",
        "Engine Oil",
    ) == {
        "interval_km": 10000,
        "interval_months": 12,
        "action": "replace",
    }

    assert data_manager.get_service_interval(
        "Honda City 2025",
        "Brake Pads",
    ) == {
        "interval_km": 10000,
        "interval_months": 12,
        "action": "inspect",
    }

    assert data_manager.get_service_interval(
        "Honda City 2025",
        "Spark Plugs",
    ) == {
        "interval_km": 100000,
        "interval_months": 0,
        "action": "replace",
    }

    assert data_manager.get_service_interval(
        "Honda City 2025",
        "Tyres",
    ) == {
        "interval_km": 10000,
        "interval_months": 0,
        "action": "rotate",
    }

    assert data_manager.get_service_interval(
        "Honda City 2025",
        "Engine Air Filter",
    ) == {
        "interval_km": 30000,
        "interval_months": 0,
        "action": "replace",
    }

    assert data_manager.get_service_interval(
        "Honda City 2025",
        "Coolant",
    ) == {
        "interval_km": 200000,
        "interval_months": 120,
        "action": "replace",
        "repeat_km": 100000,
        "repeat_months": 60,
    }


def test_mazda3_manufacturer_schedule():
    expected = {
        "Engine Oil": (
            16000,
            12,
            "replace",
        ),
        "Brake Pads": (
            16000,
            12,
            "inspect",
        ),
        "Spark Plugs": (
            120000,
            0,
            "replace",
        ),
        "Tyres": (
            16000,
            0,
            "rotate",
        ),
        "Engine Air Filter": (
            48000,
            36,
            "replace",
        ),
    }

    for part, (km, months, action) in expected.items():
        rule = data_manager.get_service_interval(
            "Mazda 3 Hatchback 2020",
            part,
        )

        assert rule["interval_km"] == km
        assert rule["interval_months"] == months
        assert rule["action"] == action

    assert data_manager.get_service_interval(
        "Mazda 3 Hatchback 2020",
        "Coolant",
    ) == {
        "interval_km": 192000,
        "interval_months": 120,
        "action": "replace",
        "repeat_km": 96000,
        "repeat_months": 60,
    }


def test_hyundai_elantra_manufacturer_schedule():
    expected = {
        "Engine Oil": (
            15000,
            12,
            "replace",
        ),
        "Brake Pads": (
            15000,
            12,
            "inspect",
        ),
        "Spark Plugs": (
            160000,
            0,
            "replace",
        ),
        "Tyres": (
            12000,
            0,
            "rotate",
        ),
        "Engine Air Filter": (
            45000,
            36,
            "replace",
        ),
    }

    for part, (km, months, action) in expected.items():
        rule = data_manager.get_service_interval(
            "Hyundai Elantra 2021",
            part,
        )

        assert rule["interval_km"] == km
        assert rule["interval_months"] == months
        assert rule["action"] == action

    assert data_manager.get_service_interval(
        "Hyundai Elantra 2021",
        "Coolant",
    ) == {
        "interval_km": 200000,
        "interval_months": 120,
        "action": "replace",
        "repeat_km": 40000,
        "repeat_months": 24,
    }


def test_kia_forte_manufacturer_schedule():
    expected = {
        "Engine Oil": (
            13000,
            12,
            "replace",
        ),
        "Brake Pads": (
            13000,
            12,
            "inspect",
        ),
        "Spark Plugs": (
            156000,
            0,
            "replace",
        ),
        "Tyres": (
            13000,
            12,
            "rotate",
        ),
        "Engine Air Filter": (
            39000,
            36,
            "replace",
        ),
    }

    for part, (km, months, action) in expected.items():
        rule = data_manager.get_service_interval(
            "Kia Forte",
            part,
        )

        assert rule["interval_km"] == km
        assert rule["interval_months"] == months
        assert rule["action"] == action

    assert data_manager.get_service_interval(
        "Kia Forte",
        "Coolant",
    ) == {
        "interval_km": 195000,
        "interval_months": 120,
        "action": "replace",
        "repeat_km": 39000,
        "repeat_months": 24,
    }

def test_history_for_part_returns_only_matching_part():
    with temp_data_files():
        data_manager.add_service({**SERVICE, "part_name": "Brake Pads"})
        data_manager.add_service({**SERVICE, "part_name": "Engine Oil"})
        result = data_manager.history_for_part("SBA1234A", "Brake Pads")
        assert len(result) == 1 and result[0]["part_name"] == "Brake Pads"
