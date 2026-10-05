"""Where a household's changes are kept, so they survive a restart.

The appliance data a person checked against the manuals ships with the code and
is never written to. What changes while people use Home Operator is kept apart
from it, in one Amazon DynamoDB item per household:

  * service_log: jobs someone said they did ("I replaced the fridge filter")
  * appliances:  appliances someone registered ("I just got a Bosch dryer")

Every tool call reads the item afresh. AgentCore Runtime may run several copies
of this server, and a change made through one has to be seen by the next call,
which can land on another. A read is one GetItem, a few milliseconds in-region.

With HOME_TABLE unset - a laptop, the tests - the household lives in memory for
the life of the process, exactly as it always has.

    uv run home-operator-reset-household     # clear the changes, keep the manuals
"""

import copy
import os

from home_operator import store

HOUSEHOLD_ID = os.environ.get("HOUSEHOLD_ID", "demo")
# A public demo should not grow without limit; past this, the oldest changes go.
MAX_ENTRIES = 300


def _table_name() -> str | None:
    return os.environ.get("HOME_TABLE") or None


class Household:
    def __init__(self, table=None, household_id: str = HOUSEHOLD_ID) -> None:
        self.household_id = household_id
        self._base = store.load_home()
        self._table = table
        if self._table is None and _table_name():
            import boto3
            region = os.environ.get("AWS_REGION", "us-east-1")
            self._table = boto3.resource("dynamodb", region_name=region).Table(_table_name())
        self._memory = copy.deepcopy(self._base) if self._table is None else None

    @property
    def persistent(self) -> bool:
        return self._table is not None

    def load(self) -> dict:
        """The household as it stands now: the checked data plus every change."""
        if self._memory is not None:
            return self._memory
        home = copy.deepcopy(self._base)
        item = self._table.get_item(Key={"household_id": self.household_id}, ConsistentRead=True).get("Item") or {}
        known = {a["id"] for a in home["appliances"]}
        for a in item.get("appliances", []):
            if a["id"] not in known:
                home["appliances"].append(_plain(a))
                known.add(a["id"])
        home["service_log"].extend(_plain(e) for e in item.get("service_log", []))
        return home

    def save(self, before: dict, after: dict) -> None:
        """Keep whatever a tool call added to the household."""
        if self._memory is not None:
            return  # the tool already changed the in-memory household
        new_log = after["service_log"][len(before["service_log"]):]
        new_appliances = after["appliances"][len(before["appliances"]):]
        if not new_log and not new_appliances:
            return
        names, values, parts = {}, {":empty": []}, []
        for field, entries in (("service_log", new_log), ("appliances", new_appliances)):
            if entries:
                names[f"#{field}"] = field
                values[f":{field}"] = entries
                parts.append(f"#{field} = list_append(if_not_exists(#{field}, :empty), :{field})")
        self._table.update_item(
            Key={"household_id": self.household_id},
            UpdateExpression="SET " + ", ".join(parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
        self._trim()

    def _trim(self) -> None:
        item = self._table.get_item(Key={"household_id": self.household_id}).get("Item") or {}
        log = item.get("service_log", [])
        if len(log) > MAX_ENTRIES:
            self._table.update_item(
                Key={"household_id": self.household_id},
                UpdateExpression="SET service_log = :kept",
                ExpressionAttributeValues={":kept": log[-MAX_ENTRIES:]},
            )

    def reset(self) -> None:
        if self._memory is not None:
            self._memory = copy.deepcopy(self._base)
        else:
            self._table.delete_item(Key={"household_id": self.household_id})


def _plain(value):
    """DynamoDB hands numbers back as Decimal; the tools expect int."""
    from decimal import Decimal
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value == int(value) else float(value)
    return value


def reset_main() -> None:
    h = Household()
    where = f"DynamoDB table {_table_name()}" if h.persistent else "memory (HOME_TABLE is not set)"
    h.reset()
    print(f"Cleared household '{h.household_id}' in {where}. The checked manual data is untouched.")
