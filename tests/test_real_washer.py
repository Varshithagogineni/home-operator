"""The LG WM9500HKA in the demo home comes from Bedrock's reading of LG's manual, then human review."""
import json
from datetime import date
from pathlib import Path

import pytest

from home_operator import merge, store

TODAY = date(2026, 9, 21)
REVIEWED = json.loads((Path(merge.EXTRACTED_DIR) / "WM9500HKA.json").read_text())


def test_oe_names_the_hose_first_then_links_the_drain_filter_fix():
    d = store.diagnose_symptom(store.load_home(), "washer", "it's showing OE", TODAY)
    assert d["brand"] == "LG"
    assert "can't drain" in d["meaning"]
    assert d["source_page"] == 44
    assert "hose" in d["causes"][0]["short"] and not d["causes"][0]["fix_available"]
    fix = next(c for c in d["causes"] if c["fix_available"])
    assert fix["fix"] == "Clean the drain pump filter"


def test_drain_filter_repair_is_gated_on_power_and_cites_its_page():
    sessions = {}
    r = store.start_repair(store.load_home(), sessions, "washer", "clean the drain pump filter", TODAY)
    assert r["total_steps"] == 8
    assert r["step"] == "Turn off the washer, and unplug the power cord."
    assert r["awaiting_confirmation"] and "unplugged" in r["confirm_prompt"]
    assert r["source"] == "LG owner's manual, page 40"


def test_review_removed_every_interval_the_manual_does_not_state():
    intervals = {m["task"]: m["interval_days"] for m in REVIEWED["maintenance"]}
    assert "clean the drain pump filter" not in intervals
    assert "clean the water inlet filters" not in intervals
    assert intervals["run the tub clean cycle"] == 30
    assert intervals["replace the water hoses"] == 1825
    assert all(c["page"] and c["manual_says"] for c in REVIEWED["source"]["review"]["changes"])


def test_merge_replaces_an_appliance_and_everything_attached_to_it():
    home = {"appliances": [{"id": "w", "brand": "Old"}],
            "procedures": [{"id": "old-proc", "appliance_id": "w"}],
            "symptoms": [{"appliance_id": "w", "causes": []}],
            "service_log": [{"appliance_id": "w", "task": "old"}]}
    merge.merge(home, REVIEWED, appliance_id="w", nickname="Washer", room="laundry room",
                purchase_date="2019-04-12", warranty_until="2020-04-12",
                service_log=[{"task": "clean the door seal", "date": "2026-08-01", "notes": None}])
    assert [a["brand"] for a in home["appliances"]] == ["LG"]
    assert all(p["id"].startswith("wm9500hka-") for p in home["procedures"])
    linked = {c["procedure_id"] for s in home["symptoms"] for c in s["causes"] if c["procedure_id"]}
    assert linked <= {p["id"] for p in home["procedures"]}
    assert home["service_log"] == [{"appliance_id": "w", "task": "clean the door seal", "date": "2026-08-01", "notes": None}]


def test_finishing_an_unscheduled_repair_logs_it_without_touching_other_tasks():
    home, sessions = store.load_home(), {}
    door_seal_before = [i for i in store.maintenance_due(home, TODAY)["overdue"] if i["task"] == "clean the door seal"]
    assert door_seal_before

    store.start_repair(home, sessions, "washer", "clean the drain pump filter", TODAY)
    store.navigate_repair(home, sessions, "done", TODAY)
    for _ in range(6):
        store.navigate_repair(home, sessions, "next", TODAY)
    finished = store.navigate_repair(home, sessions, "next", TODAY)

    assert finished["logged"]["task"] == "clean the drain pump filter"
    assert finished["logged"]["next_due"] is None
    assert [i for i in store.maintenance_due(home, TODAY)["overdue"] if i["task"] == "clean the door seal"] == door_seal_before


@pytest.mark.parametrize("said, expected", [
    ("I replaced the water hoses", "replace the water hoses"),
    ("cleaned the door seal", "clean the door seal"),
    ("ran the tub clean cycle", "run the tub clean cycle"),
    ("clean the drain pump filter", None),
    ("cleaned it", None),
])
def test_spoken_tasks_match_only_when_most_words_agree(said, expected):
    tasks = ["clean the door seal", "run the tub clean cycle", "clean the detergent dispenser", "replace the water hoses"]
    assert store._match_task(said, tasks) == expected
