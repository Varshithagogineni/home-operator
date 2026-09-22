from datetime import date

from home_operator import store

TODAY = date(2026, 9, 17)


def home():
    return {
        "appliances": [
            {
                "id": "dw", "nickname": "Dishwasher", "room": "kitchen", "category": "dishwasher",
                "brand": "Test", "model_number": "T-DW", "purchase_date": "2024-01-01",
                "warranty_until": "2025-01-01", "consumables": [],
                "maintenance": [{"task": "clean the filter", "interval_days": 90}],
            },
            {
                "id": "fr", "nickname": "Fridge", "room": "kitchen", "category": "refrigerator",
                "brand": "Test", "model_number": "T-FR", "purchase_date": "2026-01-01",
                "warranty_until": "2027-01-01",
                "consumables": [{"name": "water filter", "part_number": "T-WF", "size": None}],
                "maintenance": [{"task": "replace the water filter", "interval_days": 180}],
            },
            {
                "id": "wm", "nickname": "Washer", "room": "laundry room", "category": "washing machine",
                "brand": "Test", "model_number": "T-WM", "purchase_date": "2026-09-10",
                "warranty_until": "2027-09-10", "consumables": [],
                "maintenance": [{"task": "run a cleaning cycle", "interval_days": 60}],
            },
        ],
        "service_log": [
            {"appliance_id": "dw", "task": "clean the filter", "date": "2026-05-01", "notes": None},
            {"appliance_id": "dw", "task": "clean the filter", "date": "2026-02-01", "notes": None},
            {"appliance_id": "fr", "task": "replace the water filter", "date": "2026-04-01", "notes": None},
        ],
    }


def test_finds_by_nickname_category_and_filler_words():
    h = home()
    assert [a["id"] for a in store.find_appliances(h, "the fridge")] == ["fr"]
    assert [a["id"] for a in store.find_appliances(h, "Refrigerator")] == ["fr"]
    assert [a["id"] for a in store.find_appliances(h, "my kitchen dishwasher")] == ["dw"]


def test_exact_match_beats_substring():
    assert [a["id"] for a in store.find_appliances(home(), "washer")] == ["wm"]


def test_describe_known_appliance():
    result = store.describe_appliance(home(), "fridge", TODAY)
    assert result["found"] is True
    assert result["warranty"] == {"status": "active", "until": "2027-01-01"}
    assert result["consumables"][0]["part_number"] == "T-WF"
    assert result["last_service"] == {"task": "replace the water filter", "date": "2026-04-01", "days_ago": 169}


def test_describe_uses_most_recent_service():
    result = store.describe_appliance(home(), "dishwasher", TODAY)
    assert result["warranty"]["status"] == "expired"
    assert result["last_service"]["date"] == "2026-05-01"


def test_unknown_appliance_lists_what_is_registered():
    result = store.describe_appliance(home(), "toaster", TODAY)
    assert result["found"] is False
    assert {a["nickname"] for a in result["known_appliances"]} == {"Dishwasher", "Fridge", "Washer"}


def test_ambiguous_query_returns_candidates():
    result = store.describe_appliance(home(), "kitchen", TODAY)
    assert result["found"] is False
    assert {c["nickname"] for c in result["candidates"]} == {"Dishwasher", "Fridge"}


def test_maintenance_due_splits_overdue_and_upcoming():
    result = store.maintenance_due(home(), TODAY, within_days=30)
    assert [(i["nickname"], i["days_overdue"]) for i in result["overdue"]] == [("Dishwasher", 49)]
    assert [(i["nickname"], i["days_until"]) for i in result["upcoming"]] == [("Fridge", 11)]


def test_never_serviced_task_counts_from_purchase_date():
    result = store.maintenance_due(home(), TODAY, within_days=30)
    assert all(i["nickname"] != "Washer" for i in result["overdue"] + result["upcoming"])
    result = store.maintenance_due(home(), TODAY, within_days=60)
    washer = next(i for i in result["upcoming"] if i["nickname"] == "Washer")
    assert washer["due_date"] == "2026-11-09" and washer["last_done"] is None


def test_home_data_is_consistent():
    h = store.load_home()
    ids = {a["id"] for a in h["appliances"]}
    assert all(e["appliance_id"] in ids for e in h["service_log"])
    assert all(p["appliance_id"] in ids for p in h["procedures"])
    assert all(s["appliance_id"] in ids for s in h["symptoms"])
    procedure_ids = {p["id"] for p in h["procedures"]}
    linked = {c["procedure_id"] for s in h["symptoms"] for c in s["causes"] if c["procedure_id"]}
    assert linked <= procedure_ids
