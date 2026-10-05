"""A household's changes survive a restart, and every server copy sees them.

A stand-in for the DynamoDB table, so no AWS is needed: it understands exactly
the two update expressions household.py writes.
"""

import copy
import re
from datetime import date
from decimal import Decimal

from home_operator import household, store


class FakeTable:
    def __init__(self):
        self.items = {}

    def get_item(self, Key, **_):
        item = self.items.get(Key["household_id"])
        return {"Item": copy.deepcopy(item)} if item is not None else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None):
        item = self.items.setdefault(Key["household_id"], {"household_id": Key["household_id"]})
        names = ExpressionAttributeNames or {}
        # Split between assignments, not on the commas inside list_append(...).
        for part in re.split(r", (?=[#\w]+ = )", UpdateExpression.removeprefix("SET ")):
            target, expr = part.split(" = ", 1)
            field = names.get(target, target)
            m = re.match(r"list_append\(if_not_exists\(#\w+, :empty\), (:\w+)\)", expr)
            if m:
                # DynamoDB returns numbers as Decimal; mimic it.
                added = _as_dynamo(ExpressionAttributeValues[m.group(1)])
                item[field] = item.get(field, []) + added
            else:
                item[field] = _as_dynamo(ExpressionAttributeValues[expr])

    def delete_item(self, Key):
        self.items.pop(Key["household_id"], None)


def _as_dynamo(value):
    if isinstance(value, list):
        return [_as_dynamo(v) for v in value]
    if isinstance(value, dict):
        return {k: _as_dynamo(v) for k, v in value.items()}
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    return copy.deepcopy(value)


def _do(h, fn):
    home = h.load()
    before = {"service_log": list(home["service_log"]), "appliances": list(home["appliances"])}
    result = fn(home)
    h.save(before, home)
    return result


TODAY = date(2026, 10, 5)


def test_a_logged_job_survives_a_restart():
    table = FakeTable()
    first = household.Household(table=table)
    _do(first, lambda home: store.log_service(home, "fridge", "replaced the water filter", TODAY))
    restarted = household.Household(table=table)
    log = restarted.load()["service_log"]
    assert any(e["task"] == "replace the water filter" and e["date"] == TODAY.isoformat() for e in log)


def test_two_server_copies_see_each_others_changes():
    """AgentCore may run several copies; a change through one must reach the next call on another."""
    table = FakeTable()
    a, b = household.Household(table=table), household.Household(table=table)
    _do(a, lambda home: store.add_appliance(home, "dryer", "Bosch", "WTG86403UC", TODAY))
    found = store.describe_appliance(b.load(), "dryer", TODAY)
    assert found["found"] and found["model_number"] == "WTG86403UC"


def test_an_added_appliance_comes_back_with_plain_numbers():
    table = FakeTable()
    h = household.Household(table=table)
    _do(h, lambda home: store.add_appliance(home, "dryer", "Bosch", "WTG86403UC", TODAY))
    dryer = next(a for a in household.Household(table=table).load()["appliances"] if a["model_number"] == "WTG86403UC")
    interval = dryer["maintenance"][0]["interval_days"]
    assert interval == 365 and isinstance(interval, int)
    # and the maintenance arithmetic still works on it
    store.maintenance_due(household.Household(table=table).load(), TODAY)


def test_the_checked_manual_data_is_never_written():
    table = FakeTable()
    h = household.Household(table=table)
    _do(h, lambda home: store.log_service(home, "washer", "cleaned the drum", TODAY))
    _do(h, lambda home: store.add_appliance(home, "dryer", "Bosch", "WTG86403UC", TODAY))
    stored = table.items["demo"]
    assert set(stored) == {"household_id", "service_log", "appliances"}
    assert len(stored["appliances"]) == 1 and len(stored["service_log"]) == 1
    assert len(household.Household(table=table)._base["appliances"]) == 5


def test_reading_tools_write_nothing():
    table = FakeTable()
    h = household.Household(table=table)
    _do(h, lambda home: store.maintenance_due(home, TODAY))
    _do(h, lambda home: store.diagnose_symptom(home, "washer", "won't drain", TODAY))
    assert table.items == {}


def test_finishing_a_repair_is_kept_too():
    table = FakeTable()
    h = household.Household(table=table)
    home = h.load()
    started = store.start_repair(home, "dishwasher", "clean the filter system", TODAY)
    step, total = started["step_number"], started["total_steps"]
    while step <= total:
        reply = _do(h, lambda home: store.navigate_repair(home, "next", started["repair"], step, TODAY, ""))
        if reply.get("finished"):
            break
        step = reply["step_number"]
    assert reply["finished"]
    log = household.Household(table=table).load()["service_log"]
    assert log[-1]["date"] == TODAY.isoformat()


def test_reset_clears_changes_but_keeps_the_manuals():
    table = FakeTable()
    h = household.Household(table=table)
    _do(h, lambda home: store.add_appliance(home, "dryer", "Bosch", "WTG86403UC", TODAY))
    h.reset()
    assert len(household.Household(table=table).load()["appliances"]) == 5


def test_without_a_table_it_works_in_memory_as_before(monkeypatch):
    monkeypatch.delenv("HOME_TABLE", raising=False)
    h = household.Household()
    assert not h.persistent
    _do(h, lambda home: store.log_service(home, "fridge", "replaced the water filter", TODAY))
    assert h.load()["service_log"][-1]["date"] == TODAY.isoformat()


def test_a_demo_household_cannot_grow_without_limit(monkeypatch):
    monkeypatch.setattr(household, "MAX_ENTRIES", 3)
    table = FakeTable()
    h = household.Household(table=table)
    for _ in range(5):
        _do(h, lambda home: store.log_service(home, "fridge", "replaced the water filter", TODAY))
    assert len(table.items["demo"]["service_log"]) == 3
