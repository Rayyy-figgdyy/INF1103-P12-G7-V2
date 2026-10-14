"""Check that main passes raw brake-pad history to the existing AI pipeline."""
import data_manager
import main


def test_main_includes_inspections_with_replacement_history(monkeypatch):
    # Three replacements make the optional AI history analysis eligible.
    history = [
        {"part_name": "Brake Pads", "service_action": "replace",
         "service_date": date, "service_odometer": km}
        for date, km in [("01-01-2021", 20_000), ("01-01-2022", 40_000),
                         ("01-01-2023", 60_000)]
    ]
    history.append({"part_name": "Brake Pads", "service_action": "inspect",
                    "service_date": "01-01-2024", "service_odometer": 65_000})

    # Use sample records without reading or writing the real JSON files.
    monkeypatch.setattr(data_manager, "history_for_part", lambda plate, part: history)
    user = {"license_plate": "TEST123", "car_model": "Mazda 3 Hatchback 2020",
            "car_condition": "Used", "coe_expiry_date": "01-01-2030"}
    service = {"service_date": "01-01-2024", "service_odometer": 65_000,
               "service_action": "inspect"}
    interval = {"interval_km": 16_000, "interval_months": 12, "action": "inspect"}
    record = main.build_check_record(user, "Brake Pads", service, 70_000, interval, 2020)
    assert record["history_context"]["eligible"] is True
    assert record["history_context"]["replacement_count"] == 3
    assert record["brake_pad_history"] == history
    assert any(item["service_action"] == "inspect" for item in record["brake_pad_history"])


def test_main_falls_back_without_three_replacements(monkeypatch):
    history = [
        {"part_name": "Brake Pads", "service_action": "replace",
         "service_date": "01-01-2022", "service_odometer": 20_000},
        {"part_name": "Brake Pads", "service_action": "replace",
         "service_date": "01-01-2023", "service_odometer": 40_000},
    ]
    monkeypatch.setattr(data_manager, "history_for_part", lambda plate, part: history)
    user = {"license_plate": "TEST123", "car_model": "Mazda 3 Hatchback 2020",
            "car_condition": "Used", "coe_expiry_date": "01-01-2030"}
    service = {"service_date": "01-01-2023", "service_odometer": 40_000}
    interval = {"interval_km": 16_000, "interval_months": 12, "action": "inspect"}
    record = main.build_check_record(user, "Brake Pads", service, 70_000, interval, 2020)
    assert record["history_context"]["eligible"] is False
    assert "brake_pad_history" not in record
