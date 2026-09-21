import json
import re
from datetime import date, timedelta
from importlib import resources

FILLER_WORDS = {"the", "my", "our", "a", "an"}


def load_home() -> dict:
    data = resources.files("home_operator").joinpath("data")
    home = json.loads(data.joinpath("sample_home.json").read_text())
    recalls = json.loads(data.joinpath("recalls.json").read_text())
    home["recalls"] = recalls.get("by_appliance", {})
    return home


def _open_recalls(home: dict, appliance_id: str) -> list[dict]:
    return [
        {"title": r["title"], "hazard": r["hazard"], "remedy": r["remedy"], "url": r["url"], "date": r["date"]}
        for r in home.get("recalls", {}).get(appliance_id, [])
    ]


def _normalize(text: str) -> str:
    # Drop punctuation so spoken text matches keywords: "won't drain?" -> "wont drain"
    cleaned = re.sub(r"[^a-z0-9\s]", "", text.lower().replace("-", " "))
    return " ".join(w for w in cleaned.split() if w not in FILLER_WORDS)


def _names(appliance: dict) -> set[str]:
    return {
        _normalize(appliance["nickname"]),
        _normalize(appliance["category"]),
        _normalize(f'{appliance["room"]} {appliance["category"]}'),
        _normalize(f'{appliance["room"]} {appliance["nickname"]}'),
    }


def find_appliances(home: dict, query: str) -> list[dict]:
    q = _normalize(query)
    if not q:
        return []
    exact = [a for a in home["appliances"] if q in _names(a)]
    if exact:
        return exact
    return [
        a for a in home["appliances"]
        if any(q in name or name in q for name in _names(a))
    ]


def _last_service(home: dict, appliance_id: str, task: str | None = None) -> dict | None:
    entries = [
        e for e in home["service_log"]
        if e["appliance_id"] == appliance_id and (task is None or e["task"] == task)
    ]
    return max(entries, key=lambda e: e["date"], default=None)


def _brief(appliance: dict) -> dict:
    return {"nickname": appliance["nickname"], "room": appliance["room"]}


def describe_appliance(home: dict, query: str, today: date) -> dict:
    matches = find_appliances(home, query)
    if not matches:
        return {
            "found": False,
            "message": f'No appliance matching "{query}" is registered in this home.',
            "known_appliances": [_brief(a) for a in home["appliances"]],
        }
    if len(matches) > 1:
        return {
            "found": False,
            "message": f'More than one appliance matches "{query}". Ask which one.',
            "candidates": [_brief(a) for a in matches],
        }

    a = matches[0]
    warranty_until = date.fromisoformat(a["warranty_until"])
    last = _last_service(home, a["id"])
    return {
        "found": True,
        "nickname": a["nickname"],
        "room": a["room"],
        "brand": a["brand"],
        "model_number": a["model_number"],
        "warranty": {
            "status": "active" if warranty_until >= today else "expired",
            "until": a["warranty_until"],
        },
        "consumables": a["consumables"],
        "open_recalls": _open_recalls(home, a["id"]),
        "last_service": None if last is None else {
            "task": last["task"],
            "date": last["date"],
            "days_ago": (today - date.fromisoformat(last["date"])).days,
        },
    }


def maintenance_due(home: dict, today: date, within_days: int = 30) -> dict:
    within_days = max(0, min(within_days, 365))
    overdue, upcoming = [], []
    for a in home["appliances"]:
        for m in a["maintenance"]:
            last = _last_service(home, a["id"], m["task"])
            start = date.fromisoformat(last["date"] if last else a["purchase_date"])
            due = start + timedelta(days=m["interval_days"])
            item = {
                **_brief(a),
                "task": m["task"],
                "due_date": due.isoformat(),
                "last_done": last["date"] if last else None,
            }
            delta = (due - today).days
            if delta < 0:
                overdue.append({**item, "days_overdue": -delta})
            elif delta <= within_days:
                upcoming.append({**item, "days_until": delta})

    overdue.sort(key=lambda i: -i["days_overdue"])
    upcoming.sort(key=lambda i: i["days_until"])
    recalls = [
        {**_brief(a), **r}
        for a in home["appliances"]
        for r in _open_recalls(home, a["id"])
    ]
    return {
        "as_of": today.isoformat(),
        "window_days": within_days,
        "open_recalls": recalls,
        "overdue": overdue,
        "upcoming": upcoming,
    }


def _procedure(home: dict, procedure_id: str) -> dict | None:
    return next((p for p in home["procedures"] if p["id"] == procedure_id), None)


def _appliance(home: dict, appliance_id: str) -> dict | None:
    return next((a for a in home["appliances"] if a["id"] == appliance_id), None)


def diagnose_symptom(home: dict, query: str, symptom: str, today: date) -> dict:
    matches = find_appliances(home, query)
    if len(matches) != 1:
        return describe_appliance(home, query, today)

    a = matches[0]
    known = [s for s in home["symptoms"] if s["appliance_id"] == a["id"]]
    words = set(_normalize(symptom).split())
    scored = [(len(words & set(s["keywords"])), s) for s in known]
    best_score, best = max(scored, key=lambda pair: pair[0], default=(0, None))

    if best is None or best_score == 0:
        return {
            "found": False,
            **_brief(a),
            "message": f'No known cause for that on the {a["nickname"]}.',
            "known_symptoms": [s["symptom"] for s in known],
        }

    causes = []
    for c in best["causes"]:
        entry = {"cause": c["cause"], "likelihood": c["likelihood"], "fix_available": False}
        proc = _procedure(home, c["procedure_id"]) if c["procedure_id"] else None
        if proc:
            last = _last_service(home, a["id"], proc["task"])
            entry |= {
                "fix_available": True,
                "procedure_id": proc["id"],
                "fix": proc["title"],
                "minutes": proc["minutes"],
                "last_done": last["date"] if last else None,
                "days_since_last_done": (today - date.fromisoformat(last["date"])).days if last else None,
            }
        causes.append(entry)

    return {"found": True, **_brief(a), "symptom": best["symptom"], "causes": causes}


def start_repair(home: dict, sessions: dict, query: str, task: str, today: date, home_id: str = "default") -> dict:
    matches = find_appliances(home, query)
    if len(matches) != 1:
        return describe_appliance(home, query, today)

    a = matches[0]
    procs = [p for p in home["procedures"] if p["appliance_id"] == a["id"]]
    words = set(_normalize(task).split())
    scored = [(len(words & set(_normalize(f'{p["title"]} {p["task"]}').split())), p) for p in procs]
    best_score, proc = max(scored, key=lambda pair: pair[0], default=(0, None))

    if proc is None or best_score == 0:
        return {
            "started": False,
            **_brief(a),
            "message": f'No repair steps stored for that on the {a["nickname"]}.',
            "available_repairs": [p["title"] for p in procs],
        }

    sessions[home_id] = {"procedure_id": proc["id"], "step_index": 0, "confirmed": False}
    return {
        "started": True,
        **_brief(a),
        "procedure": proc["title"],
        "estimated_minutes": proc["minutes"],
        "tools_needed": proc["tools_needed"],
        "safety_note": proc["safety_note"],
        "step_number": 1,
        "total_steps": len(proc["steps"]),
        "step": proc["steps"][0],
        **_gate_fields(proc, 0, confirmed=False),
    }


def _gate_fields(proc: dict, step_index: int, confirmed: bool) -> dict:
    """A gate step will not advance until the person confirms it is safe."""
    if proc.get("gate_step") != step_index or confirmed:
        return {"awaiting_confirmation": False}
    return {"awaiting_confirmation": True, "confirm_prompt": proc["gate_prompt"]}


CONFIRM_WORDS = {"confirm", "confirmed", "done", "yes", "its off", "it is off", "unplugged", "off"}


def navigate_repair(home: dict, sessions: dict, action: str, today: date, home_id: str = "default") -> dict:
    session = sessions.get(home_id)
    if session is None:
        return {
            "active": False,
            "message": "No repair is in progress. Start one first.",
            "available_repairs": [p["title"] for p in home["procedures"]],
        }

    proc = _procedure(home, session["procedure_id"])
    a = _appliance(home, proc["appliance_id"])
    total = len(proc["steps"])
    action = _normalize(action or "next") or "next"
    at_gate = proc.get("gate_step") == session["step_index"] and not session["confirmed"]

    if action in CONFIRM_WORDS and at_gate:
        session["confirmed"] = True
        action = "next"
    elif action == "next" and at_gate:
        return {
            "active": True,
            "finished": False,
            **_brief(a),
            "procedure": proc["title"],
            "step_number": session["step_index"] + 1,
            "total_steps": total,
            "step": proc["steps"][session["step_index"]],
            "awaiting_confirmation": True,
            "confirm_prompt": proc["gate_prompt"],
        }
    elif action in CONFIRM_WORDS:
        action = "next"

    if action == "next":
        if session["step_index"] + 1 >= total:
            sessions.pop(home_id, None)
            logged = log_service(home, a["nickname"], proc["task"], today)
            return {
                "active": False,
                "finished": True,
                **_brief(a),
                "procedure": proc["title"],
                "message": f'That was the last step. {proc["title"]} is done.',
                "logged": logged,
            }
        session["step_index"] += 1
    elif action == "back":
        session["step_index"] = max(0, session["step_index"] - 1)
    elif action != "repeat":
        return {
            "active": True,
            "message": f'Unknown action "{action}".',
            "valid_actions": ["next", "back", "repeat"],
            "step_number": session["step_index"] + 1,
            "total_steps": total,
            "step": proc["steps"][session["step_index"]],
        }

    return {
        "active": True,
        "finished": False,
        **_brief(a),
        "procedure": proc["title"],
        "step_number": session["step_index"] + 1,
        "total_steps": total,
        "step": proc["steps"][session["step_index"]],
        **_gate_fields(proc, session["step_index"], session["confirmed"]),
    }


def log_service(home: dict, query: str, task: str, today: date, notes: str | None = None) -> dict:
    matches = find_appliances(home, query)
    if len(matches) != 1:
        return describe_appliance(home, query, today)

    a = matches[0]
    known_tasks = [m["task"] for m in a["maintenance"]]
    words = set(_normalize(task).split())
    scored = [(len(words & set(_normalize(t).split())), t) for t in known_tasks]
    best_score, matched = max(scored, key=lambda pair: pair[0], default=(0, None))
    recorded_task = matched if matched and best_score else task

    home["service_log"].append({
        "appliance_id": a["id"],
        "task": recorded_task,
        "date": today.isoformat(),
        "notes": notes,
    })

    next_due = None
    interval = next((m["interval_days"] for m in a["maintenance"] if m["task"] == recorded_task), None)
    if interval:
        next_due = (today + timedelta(days=interval)).isoformat()

    return {"logged": True, **_brief(a), "task": recorded_task, "date": today.isoformat(), "next_due": next_due}
