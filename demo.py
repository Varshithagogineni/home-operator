import json, urllib.request

URL = "http://127.0.0.1:8000/mcp"
_id = [0]

def call(tool, **args):
    _id[0] += 1
    body = json.dumps({"jsonrpc": "2.0", "id": _id[0], "method": "tools/call",
                       "params": {"name": tool, "arguments": args}}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-03-26",
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        payload = json.loads(r.read())
    return json.loads(payload["result"]["content"][0]["text"])

def say(line): print(f"\n\033[1m{line}\033[0m")

say('1. "Why won\'t my dishwasher drain?"')
d = call("diagnose_symptom", appliance="dishwasher", symptom="it won't drain, standing water")
for c in d["causes"]:
    fix = f' → fix: {c["fix"]} ({c["minutes"]} min, last done {c["days_since_last_done"]} days ago)' if c["fix_available"] else ""
    print(f'   [{c["likelihood"]}] {c["cause"]}{fix}')

say('2. "Walk me through cleaning the filter."')
s = call("start_repair", appliance="dishwasher", task="clean the filter")
print(f'   {s["procedure"]} — {s["total_steps"]} steps, about {s["estimated_minutes"]} minutes')
print(f'   Tools: {", ".join(s["tools_needed"])}')
print(f'   Safety: {s["safety_note"]}')
print(f'   Step {s["step_number"]}/{s["total_steps"]}: {s["step"]}')

say('3. "Next." "Next."')
for _ in range(2):
    n = call("navigate_repair", action="next")
    print(f'   Step {n["step_number"]}/{n["total_steps"]}: {n["step"]}')

say('4. [Person asks Alexa+ an unrelated question here, then] "Say that again."')
r = call("navigate_repair", action="repeat")
print(f'   Step {r["step_number"]}/{r["total_steps"]}: {r["step"]}   <- kept its place')

say('5. Finishing the rest')
while True:
    n = call("navigate_repair", action="next")
    if n.get("finished"):
        print(f'   {n["message"]}')
        print(f'   Logged automatically: {n["logged"]["task"]} on {n["logged"]["date"]}, next due {n["logged"]["next_due"]}')
        break
    print(f'   Step {n["step_number"]}/{n["total_steps"]}: {n["step"]}')

say('6. "Anything else I should take care of?"')
m = call("get_maintenance_due")
for i in m["overdue"]:
    print(f'   OVERDUE by {i["days_overdue"]} days: {i["nickname"]} — {i["task"]}')
for i in m["upcoming"]:
    print(f'   In {i["days_until"]} days: {i["nickname"]} — {i["task"]}')
