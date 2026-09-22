"""Put a reviewed manual extraction into the home data as a real appliance."""
import json
from pathlib import Path

HOME_FILE = Path(__file__).parent / "data" / "sample_home.json"
EXTRACTED_DIR = Path(__file__).parent / "data" / "extracted"


def merge(home: dict, extracted: dict, *, appliance_id: str, nickname: str, room: str,
          purchase_date: str, warranty_until: str, service_log: list[dict]) -> dict:
    """Replace any appliance with this id, and everything attached to it, with the extracted one."""
    prefix = extracted["model_number"].lower() + "-"

    home["appliances"] = [a for a in home["appliances"] if a["id"] != appliance_id]
    home["procedures"] = [p for p in home["procedures"] if p["appliance_id"] != appliance_id]
    home["symptoms"] = [s for s in home["symptoms"] if s["appliance_id"] != appliance_id]
    home["service_log"] = [e for e in home["service_log"] if e["appliance_id"] != appliance_id]

    home["appliances"].append({
        "id": appliance_id,
        "nickname": nickname,
        "room": room,
        "category": extracted["category"],
        "brand": extracted["brand"],
        "model_number": extracted["model_number"],
        "purchase_date": purchase_date,
        "warranty_until": warranty_until,
        "consumables": extracted["consumables"],
        "maintenance": extracted["maintenance"],
        "source": extracted["source"],
    })
    for p in extracted["procedures"]:
        home["procedures"].append({
            **{k: v for k, v in p.items() if k != "gate_prompt"},
            "id": prefix + p["id"],
            "appliance_id": appliance_id,
            "gate_step": 0 if p.get("gate_prompt") else None,
            "gate_prompt": p.get("gate_prompt"),
        })
    for s in extracted["symptoms"]:
        home["symptoms"].append({
            **s,
            "appliance_id": appliance_id,
            "causes": [{**c, "procedure_id": prefix + c["procedure_id"] if c["procedure_id"] else None}
                       for c in s["causes"]],
        })
    home["service_log"].extend({"appliance_id": appliance_id, **e} for e in service_log)
    return home


APPLIANCES = [
    {"file": "WM9500HKA.json", "appliance_id": "washer-1", "nickname": "Washer", "room": "laundry room",
     "purchase_date": "2019-04-12", "warranty_until": "2020-04-12",
     "service_log": [
         {"task": "clean the door seal", "date": "2026-08-01", "notes": None},
         {"task": "run the tub clean cycle", "date": "2026-09-05", "notes": None},
         {"task": "clean the detergent dispenser", "date": "2026-08-25", "notes": None},
     ]},
    {"file": "WSEP4727F.json", "appliance_id": "oven-1", "nickname": "Oven", "room": "kitchen",
     "purchase_date": "2023-07-15", "warranty_until": "2024-07-15", "service_log": []},
]


def main() -> None:
    home = json.loads(HOME_FILE.read_text())
    for spec in APPLIANCES:
        extracted = json.loads((EXTRACTED_DIR / spec["file"]).read_text())
        merge(home, extracted, **{k: v for k, v in spec.items() if k != "file"})
        print(f"Merged {extracted['brand']} {extracted['model_number']} as {spec['appliance_id']}.")
    home["_note"] = ("Demo household: real appliance models and their manufacturer manuals, with seeded "
                     "service history. Appliances marked brand 'Sample' are placeholders still to be replaced.")
    HOME_FILE.write_text(json.dumps(home, indent=2) + "\n")


if __name__ == "__main__":
    main()
