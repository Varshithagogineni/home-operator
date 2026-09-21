from datetime import date

import pytest

from home_operator import store

TODAY = date(2026, 9, 17)


@pytest.fixture
def home():
    return store.load_home()


def test_add_appliance_gets_a_schedule_for_its_type(home):
    result = store.add_appliance(home, "new dishwasher", "Bosch", "she33t-52uc", TODAY, room="kitchen")
    assert result["added"] is True
    assert result["model_number"] == "SHE33T-52UC"
    assert result["maintenance_schedule"] == ["clean the filter"]
    assert result["recall_check"] == "queued"
    assert any(a["model_number"] == "SHE33T-52UC" for a in home["appliances"])


@pytest.mark.parametrize("said, category", [
    ("fridge", "refrigerator"),
    ("the washer in the basement", "washing machine"),
    ("washing machine", "washing machine"),
    ("dishwasher", "dishwasher"),
])
def test_spoken_types_map_to_one_category(home, said, category):
    result = store.add_appliance(home, said, "Brand", f"MODEL-{category}", TODAY)
    added = next(a for a in home["appliances"] if a["model_number"] == f"MODEL-{category}".upper())
    assert added["category"] == category


def test_same_model_is_not_added_twice(home):
    store.add_appliance(home, "dryer", "LG", "DLE3400W", TODAY)
    again = store.add_appliance(home, "dryer", "LG", "dle-3400w", TODAY)
    assert again["added"] is False
    assert sum(a["model_number"] == "DLE3400W" for a in home["appliances"]) == 1


def test_unknown_type_is_added_without_a_schedule(home):
    result = store.add_appliance(home, "espresso machine", "Breville", "BES870", TODAY)
    assert result["added"] is True
    assert result["maintenance_schedule"] == []
    assert result["note"]


def test_added_appliance_is_findable_and_shows_up_as_due(home):
    store.add_appliance(home, "water heater", "Rheem", "XE50T10", TODAY, room="garage")
    assert store.describe_appliance(home, "water heater", TODAY)["found"] is True
    later = date(2027, 10, 1)
    assert any(i["nickname"] == "Water Heater" for i in store.maintenance_due(home, later)["overdue"])


def test_pro_brief_includes_what_was_tried_today(home):
    store.log_service(home, "dishwasher", "clean the filter", TODAY)
    brief = store.prepare_pro_brief(home, "dishwasher", TODAY, symptom="still won't drain")
    assert brief["found"] is True
    assert "SAMPLE-DW-01" in brief["brief"]
    assert "Problem: still won't drain." in brief["brief_lines"]
    assert any("Already tried today: clean the filter" in line for line in brief["brief_lines"])


def test_pro_brief_lists_a_repeated_attempt_once(home):
    store.log_service(home, "dishwasher", "clean the filter", TODAY)
    store.log_service(home, "dishwasher", "clean the filter", TODAY)
    brief = store.prepare_pro_brief(home, "dishwasher", TODAY)
    tried = next(line for line in brief["brief_lines"] if line.startswith("Already tried today"))
    assert tried.count("clean the filter") == 1


def test_pro_brief_flags_a_recall_as_free_manufacturer_repair(home):
    home["recalls"] = {"dishwasher-1": [{
        "title": "Recall", "hazard": "Fire", "remedy": "Free repair", "url": "https://cpsc.gov/x",
        "date": "2021-06-16", "recall_number": "1", "matched_code": "X"}]}
    brief = store.prepare_pro_brief(home, "dishwasher", TODAY)
    assert brief["open_recalls"]
    assert "free" in brief["advice"] and "https://cpsc.gov/x" in brief["advice"]


def test_pro_brief_points_to_warranty_when_still_covered(home):
    brief = store.prepare_pro_brief(home, "washer", TODAY)
    assert brief["under_warranty"] is True
    assert "warranty" in brief["advice"]


def test_pro_brief_for_unknown_appliance_lists_known_ones(home):
    brief = store.prepare_pro_brief(home, "toaster", TODAY)
    assert brief["found"] is False and brief["known_appliances"]
