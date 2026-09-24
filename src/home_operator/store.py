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


def recall_sentence(nickname: str, recall: dict) -> str:
    """The exact words to say about a recall.

    A recall names model numbers, not serial numbers, so a match means this
    appliance *may* be affected - saying it is recalled would be wrong, and
    telling someone to stop using a working appliance on a maybe is worse. The
    wording is built here, once, so that nothing downstream has to get it right
    from raw data. It is returned to callers as say_first, and a caller that
    speaks must say it exactly as written.
    """
    hazard = (recall.get("hazard") or "").strip()
    if hazard and not hazard.endswith("."):
        hazard += "."
    parts = [
        f"Before anything else, heads up. Your {nickname.lower()}'s model is named "
        "in a safety recall, so it may be affected."
    ]
    if hazard:
        parts.append(hazard)
    parts.append("Check the serial number against the notice. If yours is included, the fix is free.")
    return " ".join(parts)


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
    recalls = _open_recalls(home, a["id"])
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
        "open_recalls": recalls,
        **({"say_first": recall_sentence(a["nickname"], recalls[0])} if recalls else {}),
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
        **({"say_first": recall_sentence(recalls[0]["nickname"], recalls[0])} if recalls else {}),
        "overdue": overdue,
        "upcoming": upcoming,
    }


def _stem(word: str) -> str:
    """Crude stemming so "replaced" matches "replace" and "hoses" matches "hose"."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    return word[:-1] if word.endswith("e") and len(word) > 3 else word


def _tokens(text: str) -> set[str]:
    """Words and their stems, plus error codes rejoined: "F-9" and "F 9" both become "f9", as stored.

    Stemming matters here because people and manuals conjugate differently: someone says the furnace
    won't "blow", the manual says "blowing".
    """
    words = _normalize(text).split()
    tokens = set(words) | {_stem(w) for w in words}
    tokens.update(a + b for a, b in zip(words, words[1:]) if a.isalpha() and len(a) <= 2 and b.isdigit())
    return tokens


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
    words = _tokens(symptom)
    scored = [(len(words & _tokens(" ".join(s["keywords"]))), s) for s in known]
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
        entry = {"cause": c["cause"], "short": c.get("short", c["cause"]), "likelihood": c["likelihood"], "fix_available": False}
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

    return {
        "found": True,
        **_brief(a),
        "brand": a["brand"],
        "symptom": best["symptom"],
        "meaning": best.get("meaning"),
        "source_page": best.get("source_page"),
        "causes": causes,
    }


def start_repair(home: dict, query: str, task: str, today: date) -> dict:
    matches = find_appliances(home, query)
    if len(matches) != 1:
        return describe_appliance(home, query, today)

    a = matches[0]
    procs = [p for p in home["procedures"] if p["appliance_id"] == a["id"]]
    proc = _best_procedure(procs, task)

    if proc is None:
        return {
            "started": False,
            **_brief(a),
            "message": f'No repair steps stored for that on the {a["nickname"]}.',
            "available_repairs": [p["title"] for p in procs],
        }

    return {
        "started": True,
        **_brief(a),
        "repair": proc["id"],
        "say_first": _opening_line(proc),
        "procedure": proc["title"],
        "estimated_minutes": proc["minutes"],
        "tools_needed": proc["tools_needed"],
        "safety_note": proc["safety_note"],
        "step_number": 1,
        "total_steps": len(proc["steps"]),
        "step": proc["steps"][0],
        "source": _source(home, a, proc),
        **_gate_fields(proc, 0),
    }


def _opening_line(proc: dict) -> str:
    """The exact words that open a repair: the warning, the first step, the gate.

    Composed here rather than left to whoever is speaking. A model asked to
    summarise a safety note produced "open the drain filter will cause water to
    overflow" - grammatically broken, and the warning is the part that matters
    most. Anything safety-critical is written once, in full sentences, and
    spoken verbatim.
    """
    parts: list[str] = []
    note = (proc.get("safety_note") or "").strip()
    if note:
        parts.append(note if note.endswith((".", "!", "?")) else note + ".")
    first = (proc["steps"][0] or "").strip()
    if first:
        parts.append(first if first.endswith((".", "!", "?")) else first + ".")
    if proc.get("gate_step") == 0 and proc.get("gate_prompt"):
        parts.append(proc["gate_prompt"].strip())
    return " ".join(parts)


def _best_procedure(procs: list[dict], task: str) -> dict | None:
    """The stored procedure a spoken task refers to, or None."""
    words = set(_normalize(task).split())
    if not words:
        return None
    scored = [
        (len(words & set(_normalize(f'{p["title"]} {p["task"]}').split())), p)
        for p in procs
    ]
    best_score, proc = max(scored, key=lambda pair: pair[0], default=(0, None))
    return proc if best_score else None


def _resolve_procedure(home: dict, repair: str) -> dict | None:
    """Find the procedure a caller names, by stored id or by what they said.

    The id is what start_repair hands back, so a well-behaved caller passes it
    straight through. Spoken words are accepted too, because a model relaying a
    conversation may paraphrase.

    Matching includes the appliance's own names. Three appliances in this home
    have a procedure about an air filter, so "replace the furnace air filter"
    was resolving to the fridge: the words that distinguish them are the ones
    naming the machine, not the job.
    """
    if not repair:
        return None
    for proc in home["procedures"]:
        if proc["id"] == repair:
            return proc

    words = set(_normalize(repair).split())
    if not words:
        return None
    best_score, best = 0, None
    for proc in home["procedures"]:
        appliance = _appliance(home, proc["appliance_id"])
        described = f'{proc["title"]} {proc["task"]}'
        if appliance:
            described += f' {appliance["nickname"]} {appliance["category"]} {appliance["room"]}'
        score = len(words & set(_normalize(described).split()))
        if score > best_score:
            best_score, best = score, proc
    return best


def _source(home: dict, appliance: dict, proc: dict) -> str | None:
    """Where a procedure's steps come from, e.g. "LG owner's manual, page 40"."""
    if not proc.get("source_page"):
        return None
    return f"{appliance['brand']} owner's manual, page {proc['source_page']}"


def _gate_fields(proc: dict, step_index: int) -> dict:
    """A gate step will not advance on "next" until the person confirms it is safe.

    Whether the gate has been cleared is not remembered anywhere: clearing it
    means moving past it, so the step number alone says where things stand. Going
    back to a gate step asks again, which is the safe behaviour.
    """
    if proc.get("gate_step") != step_index:
        return {"awaiting_confirmation": False}
    return {"awaiting_confirmation": True, "confirm_prompt": proc["gate_prompt"]}


CONFIRM_WORDS = {"confirm", "confirmed", "done", "yes", "its off", "it is off", "unplugged", "off"}

# Clearing a safety gate is stricter than agreeing to something. The gate asks a
# question about the machine - "tell me when it is off and unplugged" - so the
# answer has to be about the machine. A bare "yes" does not count: the model
# that caused this rule turned "yes please", said in answer to "want me to walk
# you through it?", into a cleared power-off gate. If someone only says yes,
# they get asked again, which costs them two seconds.
GATE_CONFIRM_WORDS = {
    "off", "unplugged", "disconnected", "done", "confirm", "confirmed", "isolated",
}


def _clamp_step(step: int | None, total: int) -> int:
    """Turn a caller's 1-based step number into a safe 0-based index."""
    try:
        index = int(step) - 1
    except (TypeError, ValueError):
        index = 0
    return max(0, min(index, total - 1))


def _is_confirmation(said: str) -> bool:
    """Whether these are a person's words confirming a machine is safe."""
    return bool(set(_normalize(said).split()) & GATE_CONFIRM_WORDS)


def navigate_repair(
    home: dict,
    action: str,
    repair: str,
    step: int | None,
    today: date,
    said: str = "",
) -> dict:
    """Move through a repair. The caller says which repair and which step.

    Nothing is stored between calls. The first version of this kept progress in
    the server's memory, which worked on one laptop and broke the moment the
    tools ran on AgentCore Runtime, where a second call can land on a different
    copy of the container that never saw the repair start. Carrying the place in
    the call itself removes the problem rather than coordinating state, and it
    matches how a voice assistant calls tools: one shot, no memory.
    """
    proc = _resolve_procedure(home, repair)
    if proc is None:
        return {
            "active": False,
            "message": (
                "I need to know which repair. Start one first, then pass back the "
                "repair id and step number from that reply."
            ),
            "available_repairs": [p["title"] for p in home["procedures"]],
        }

    a = _appliance(home, proc["appliance_id"])
    total = len(proc["steps"])
    index = _clamp_step(step, total)
    action = _normalize(action or "next") or "next"
    at_gate = proc.get("gate_step") == index
    # A safety gate is cleared by what the person said, never by a caller simply
    # asking to clear it. A model once turned a vague "yes please" into
    # action="done" and sent someone to open a drain filter on a washer that was
    # still plugged in and full of water. So "done" alone is not enough: the
    # person's own words have to carry a confirmation.
    confirming = action in CONFIRM_WORDS and (not at_gate or _is_confirmation(said))

    if at_gate and not confirming and (action == "next" or action in CONFIRM_WORDS):
        # Hold here. The person has to say the machine is safe first.
        return {
            "active": True,
            "finished": False,
            **_brief(a),
            "repair": proc["id"],
            "procedure": proc["title"],
            "step_number": index + 1,
            "total_steps": total,
            "step": proc["steps"][index],
            "awaiting_confirmation": True,
            "confirm_prompt": proc["gate_prompt"],
        }

    if confirming:
        action = "next"

    if action == "next":
        if index + 1 >= total:
            logged = log_service(home, a["nickname"], proc["task"], today)
            return {
                "active": False,
                "finished": True,
                **_brief(a),
                "repair": proc["id"],
                "procedure": proc["title"],
                "message": f'That was the last step. {proc["title"]} is done.',
                "logged": logged,
            }
        index += 1
    elif action == "back":
        index = max(0, index - 1)
    elif action != "repeat":
        return {
            "active": True,
            "message": f'Unknown action "{action}".',
            "valid_actions": ["next", "back", "repeat", "done"],
            "repair": proc["id"],
            "step_number": index + 1,
            "total_steps": total,
            "step": proc["steps"][index],
        }

    return {
        "active": True,
        "finished": False,
        **_brief(a),
        "repair": proc["id"],
        "procedure": proc["title"],
        "step_number": index + 1,
        "total_steps": total,
        "step": proc["steps"][index],
        "source": _source(home, a, proc),
        **_gate_fields(proc, index),
    }


def _match_task(said: str, known_tasks: list[str]) -> str | None:
    """The scheduled task this refers to, or None. Most of the task's words must appear:
    sharing one word ("clean") isn't enough, or cleaning one part would log another."""
    words = {_stem(w) for w in _normalize(said).split()}
    best, best_share = None, 0.0
    for known in known_tasks:
        task_words = {_stem(w) for w in _normalize(known).split()}
        share = len(words & task_words) / len(task_words)
        if share > best_share:
            best, best_share = known, share
    return best if best_share >= 0.6 else None


def log_service(home: dict, query: str, task: str, today: date, notes: str | None = None) -> dict:
    matches = find_appliances(home, query)
    if len(matches) != 1:
        return describe_appliance(home, query, today)

    a = matches[0]
    recorded_task = _match_task(task, [m["task"] for m in a["maintenance"]]) or task.strip()

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


# Standard schedules by appliance type, used until a manual is processed.
MAINTENANCE_TEMPLATES = {
    "dishwasher": [{"task": "clean the filter", "interval_days": 90}],
    "furnace": [{"task": "replace the air filter", "interval_days": 90},
                {"task": "professional tune-up", "interval_days": 365}],
    "refrigerator": [{"task": "replace the water filter", "interval_days": 180}],
    "washing machine": [{"task": "run a cleaning cycle", "interval_days": 30}],
    "dryer": [{"task": "clean the vent duct", "interval_days": 365}],
    "water heater": [{"task": "flush the tank", "interval_days": 365}],
}

CATEGORY_WORDS = {
    "dishwasher": "dishwasher",
    "furnace": "furnace",
    "fridge": "refrigerator",
    "refrigerator": "refrigerator",
    "washer": "washing machine",
    "washing machine": "washing machine",
    "dryer": "dryer",
    "water heater": "water heater",
}


def _category(text: str) -> str:
    t = _normalize(text)
    for word in sorted(CATEGORY_WORDS, key=len, reverse=True):
        if word in t:
            return CATEGORY_WORDS[word]
    return t


def add_appliance(home: dict, kind: str, brand: str, model_number: str, today: date,
                  room: str | None = None, nickname: str | None = None) -> dict:
    model_key = re.sub(r"[^A-Z0-9]", "", model_number.upper())
    for a in home["appliances"]:
        if re.sub(r"[^A-Z0-9]", "", a["model_number"].upper()) == model_key:
            return {"added": False, **_brief(a), "message": f'That {a["nickname"].lower()} is already registered.'}

    category = _category(kind)
    schedule = MAINTENANCE_TEMPLATES.get(category, [])
    appliance = {
        "id": f"{category.replace(' ', '-')}-{len(home['appliances']) + 1}",
        "nickname": nickname or category.title(),
        "room": room or "home",
        "category": category,
        "brand": brand.strip(),
        "model_number": model_number.strip().upper(),
        "purchase_date": today.isoformat(),
        "warranty_until": (today + timedelta(days=365)).isoformat(),
        "consumables": [],
        "maintenance": [dict(m) for m in schedule],
    }
    home["appliances"].append(appliance)
    return {
        "added": True,
        **_brief(appliance),
        "brand": appliance["brand"],
        "model_number": appliance["model_number"],
        "maintenance_schedule": [m["task"] for m in schedule],
        "warranty_assumed_until": appliance["warranty_until"],
        "recall_check": "queued",
        "note": None if schedule else "No standard schedule for this type yet; add one from the manual.",
    }


def prepare_pro_brief(home: dict, query: str, today: date, symptom: str | None = None) -> dict:
    matches = find_appliances(home, query)
    if len(matches) != 1:
        return describe_appliance(home, query, today)

    a = matches[0]
    purchased = date.fromisoformat(a["purchase_date"])
    age_years = round((today - purchased).days / 365, 1)
    under_warranty = date.fromisoformat(a["warranty_until"]) >= today
    tried_today = list(dict.fromkeys(
        e["task"] for e in home["service_log"]
        if e["appliance_id"] == a["id"] and e["date"] == today.isoformat()
    ))
    history = sorted((e for e in home["service_log"] if e["appliance_id"] == a["id"]),
                     key=lambda e: e["date"], reverse=True)[:3]
    recalls = _open_recalls(home, a["id"])

    lines = [
        f'{a["brand"]} {a["nickname"].lower()}, model {a["model_number"]}, about {age_years:g} years old.',
        f'Warranty: {"active until " + a["warranty_until"] if under_warranty else "expired " + a["warranty_until"]}.',
    ]
    if symptom:
        lines.append(f"Problem: {symptom.strip().rstrip('.')}.")
    if tried_today:
        lines.append(f'Already tried today: {", ".join(tried_today)}. It did not fix the problem.')
    if history:
        lines.append("Recent service: " + "; ".join(f'{e["task"]} on {e["date"]}' for e in history) + ".")

    advice = None
    if recalls:
        advice = ("This model is named in a safety recall. Check whether your serial number is included, and "
                  "contact the manufacturer before paying for a repair: recall repairs are free. " + (recalls[0]["url"] or ""))
    elif under_warranty:
        advice = "Still under warranty. Contact the manufacturer before booking a paid repair."

    return {
        "found": True,
        **_brief(a),
        "brief": " ".join(lines),
        "brief_lines": lines,
        "open_recalls": recalls,
        "under_warranty": under_warranty,
        "advice": advice,
    }
