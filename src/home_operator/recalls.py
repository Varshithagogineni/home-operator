"""Check appliances against US Consumer Product Safety Commission recalls.

This is slow-lane work: it calls a public API and can take seconds, so it runs
ahead of time and saves results to data/recalls.json. Tools only read that file.
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from home_operator import store

CPSC_URL = "https://www.saferproducts.gov/RestWebServices/Recall"
RECALLS_FILE = Path(__file__).parent / "data" / "recalls.json"

# A model code in a recall must be this long, and mix letters and digits,
# so serial ranges ("9209") and dates don't match everything.
MIN_CODE_LENGTH = 5


def fetch_recalls(product_name: str, timeout: float = 20) -> list[dict]:
    query = urllib.parse.urlencode({"format": "json", "ProductName": product_name})
    req = urllib.request.Request(f"{CPSC_URL}?{query}", headers={"User-Agent": "home-operator"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _normalize_model(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _recall_text(recall: dict) -> str:
    parts = [recall.get("Title", ""), recall.get("Description", "")]
    parts += [p.get("Name", "") for p in recall.get("Products", [])]
    parts += [m.get("Name", "") for m in recall.get("Manufacturers", [])]
    return " ".join(parts)


def _model_codes(text: str) -> set[str]:
    codes = set()
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{3,}", text):
        code = _normalize_model(token)
        if len(code) >= MIN_CODE_LENGTH and re.search(r"[A-Z]", code) and re.search(r"\d", code):
            codes.add(code)
    return codes


def match_recalls(appliance: dict, recalls: list[dict]) -> list[dict]:
    """Recalls naming this appliance's brand and a model code its model number starts with."""
    brand = re.compile(rf"\b{re.escape(appliance['brand'])}\b", re.IGNORECASE)
    model = _normalize_model(appliance["model_number"])
    matches = []
    for recall in recalls:
        text = _recall_text(recall)
        if not brand.search(text):
            continue
        hit = next((c for c in sorted(_model_codes(text), key=len, reverse=True) if model.startswith(c)), None)
        if not hit:
            continue
        matches.append({
            "recall_number": recall.get("RecallNumber"),
            "date": (recall.get("RecallDate") or "")[:10],
            "title": recall.get("Title"),
            "hazard": next((h["Name"] for h in recall.get("Hazards", []) if h.get("Name")), None),
            "remedy": next((r["Name"] for r in recall.get("Remedies", []) if r.get("Name")), None),
            "url": recall.get("URL"),
            "matched_code": hit,
        })
    return matches


def check_home(home: dict, fetch=fetch_recalls) -> dict:
    by_category: dict[str, list[dict]] = {}
    results = {}
    for a in home["appliances"]:
        if a["category"] not in by_category:
            by_category[a["category"]] = fetch(a["category"])
        results[a["id"]] = match_recalls(a, by_category[a["category"]])
    return {"checked_on": date.today().isoformat(), "by_appliance": results}


def main() -> None:
    home = store.load_home()
    result = check_home(home)
    RECALLS_FILE.write_text(json.dumps(result, indent=2) + "\n")
    found = sum(len(v) for v in result["by_appliance"].values())
    print(f"Checked {len(home['appliances'])} appliances against CPSC recalls: {found} open recall(s).")
    for a in home["appliances"]:
        for r in result["by_appliance"][a["id"]]:
            print(f"  {a['nickname']}: {r['title']} ({r['url']})")


if __name__ == "__main__":
    main()
