import json
from datetime import date
from pathlib import Path

from home_operator import recalls, store

# Real records from the CPSC Recalls API (public domain), trimmed to the fields used.
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "cpsc_dishwashers.json").read_text())


def appliance(brand, model, category="dishwasher", id_="dw"):
    return {"id": id_, "nickname": "Dishwasher", "room": "kitchen", "category": category,
            "brand": brand, "model_number": model}


def test_full_model_number_matches_the_recalled_prefix():
    # The 2017 BSH recall lists "Model number beginning with" SHE33T.
    found = recalls.match_recalls(appliance("Bosch", "SHE33T52UC"), FIXTURE)
    assert len(found) == 1
    assert "BSH" in found[0]["title"]
    assert found[0]["matched_code"] == "SHE33T"
    assert found[0]["hazard"] and found[0]["remedy"] and found[0]["url"]


def test_model_punctuation_and_case_are_ignored():
    assert recalls.match_recalls(appliance("bosch", "she33t-52uc"), FIXTURE)


def test_wrong_brand_does_not_match_even_with_a_matching_model():
    assert recalls.match_recalls(appliance("Whirlpool", "SHE33T52UC"), FIXTURE) == []


def test_unrelated_model_does_not_match():
    assert recalls.match_recalls(appliance("Bosch", "SHXM4AY55N"), FIXTURE) == []


def test_short_brand_matches_only_as_a_whole_word():
    # "GE" must not match inside words like "range" or "hinge".
    found = recalls.match_recalls(appliance("GE", "GSD6100N00BB"), FIXTURE)
    assert [r["recall_number"] for r in found] == [r["RecallNumber"] for r in FIXTURE if r["Title"].startswith("GE ")]


def test_serial_ranges_and_dates_are_not_treated_as_model_codes():
    codes = recalls._model_codes("Serial range FD 9209 - 9403, made 052610, model SHE33T")
    assert "SHE33T" in codes
    assert not {"9209", "9403", "052610"} & codes


def test_check_home_fetches_each_category_once():
    calls = []

    def fake_fetch(product):
        calls.append(product)
        return FIXTURE if product == "dishwasher" else []

    home = {"appliances": [
        appliance("Bosch", "SHE33T52UC", id_="dw-1"),
        appliance("Bosch", "SHXM4AY55N", id_="dw-2"),
        appliance("Sample", "SAMPLE-FN-80", category="furnace", id_="fn-1"),
    ]}
    result = recalls.check_home(home, fetch=fake_fetch)
    assert sorted(calls) == ["dishwasher", "furnace"]
    assert len(result["by_appliance"]["dw-1"]) == 1
    assert result["by_appliance"]["dw-2"] == []


def test_open_recalls_appear_in_lookups_and_maintenance(monkeypatch):
    home = store.load_home()
    home["recalls"] = {"dishwasher-1": [{
        "title": "Test recall", "hazard": "Fire hazard", "remedy": "Stop using it",
        "url": "https://example.gov/r", "date": "2020-01-01", "recall_number": "1", "matched_code": "X"}]}
    today = date(2026, 9, 17)

    appliance_view = store.describe_appliance(home, "dishwasher", today)
    assert appliance_view["open_recalls"][0]["hazard"] == "Fire hazard"

    due = store.maintenance_due(home, today)
    assert due["open_recalls"][0]["nickname"] == "Dishwasher"
    assert store.describe_appliance(home, "furnace", today)["open_recalls"] == []
