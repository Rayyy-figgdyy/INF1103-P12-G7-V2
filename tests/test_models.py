"""Tests for the domain classes: encapsulation with @property and @setter (Week 9)."""
from models.car import Car
from models.user_profile import UserProfile


def make_user() -> UserProfile:
    return UserProfile("Darren", "SBA1234A", "Honda City 2025", "Brand New", "12-10-2030")


def test_setters_change_name_and_coe_date():
    user = make_user()
    user.name = "  Darren Ng "
    user.coe_expiry_date = "01-01-2031"
    assert user.name == "Darren Ng"
    assert user.to_dict()["coe_expiry_date"] == "01-01-2031"


def test_name_setter_rejects_an_empty_name():
    user = make_user()
    try:
        user.name = "   "
    except ValueError:
        assert user.name == "Darren"          # unchanged
        return
    raise AssertionError("an empty name should raise ValueError")


def test_coe_setter_rejects_an_invalid_date():
    user = make_user()
    try:
        user.coe_expiry_date = "31-02-2030"   # there is no 31 February
    except ValueError:
        assert user.coe_expiry_date == "12-10-2030"
        return
    raise AssertionError("an invalid date should raise ValueError")


def test_plate_and_car_are_read_only():
    user = make_user()
    for attribute in ("license_plate", "car_model", "car_condition"):
        try:
            setattr(user, attribute, "changed")
        except AttributeError:
            continue
        raise AssertionError(f"{attribute} should be read-only")


def test_private_attributes_are_hidden():
    # Two underscores = private: Python renames (name-mangles) the attribute.
    user = make_user()
    assert not hasattr(user, "__name")
    assert user._UserProfile__name == "Darren"


def test_user_is_given_a_car_aggregation():
    car = Car("Honda City 2025", "Brand New", "manuals/honda.pdf",
              {"Engine Oil": {"action": "replace", "km": 10000, "months": 12}}, 2025)
    user = make_user()
    user.attach_car(car)
    copy = user.copy()
    assert user.car is car and copy.car is car    # the same Car is shared, not copied
