"""Add an appliance from a photo of its rating label.

Alexa+ already reads photos people upload and sees through an Echo Show camera.
In the simulator, a Nova model stands in for that step: it reads the brand,
model number and type off the label, and Home Operator's own add_appliance tool
takes it from there - the same hand-off a real Alexa+ add-on would get. Then the
government's recall database is checked for that model, live.

Reading a label is where a model is most tempted to guess, and a guessed model
number would register the wrong machine and check the wrong recall. So the model
is told to report what it cannot read rather than fill it in, and anything that
does not look like a model number is refused here, not trusted.
"""

import base64
import json
import re

from home_operator import auth, recalls

MODEL_ID = "us.amazon.nova-2-lite-v1:0"
MAX_BYTES = 8 * 1024 * 1024
FORMATS = {"image/jpeg": "jpeg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}

PROMPT = """\
This is a photo someone took of a home appliance, usually its rating label or
data plate. Read it and answer with JSON only, no other text:

{"found": true, "kind": "...", "brand": "...", "model_number": "...", "serial_number": "...", "unsure": "..."}

- kind: what the appliance is, in plain words ("dishwasher", "dryer", "refrigerator", "washer", "furnace", "water heater", "oven").
- brand: the manufacturer printed on it.
- model_number: exactly as printed after "Model", "MOD", "M/N" or "E-Nr". Copy it character by character.
- serial_number: if printed, else "".
- unsure: anything you could not read clearly, else "".

If you cannot clearly read a brand and a model number, answer {"found": false, "unsure": "<what is missing>"}.
Never guess or complete a model number. A wrong model number is worse than none.
"""

# Model numbers mix letters and digits, 5 to 20 characters, maybe with - / . or spaces.
MODEL_SHAPE = re.compile(r"^(?=.*[A-Z])(?=.*\d)[A-Z0-9][A-Z0-9 ./-]{3,24}$")


def _bedrock():
    import boto3
    return boto3.client("bedrock-runtime", region_name=auth.load_env().get("AWS_REGION", "us-east-1"))


def read_label(image: bytes, media_type: str, client=None) -> dict:
    """What the label says, or why it could not be read."""
    fmt = FORMATS.get(media_type)
    if fmt is None:
        return {"found": False, "unsure": f"unsupported image type {media_type}"}
    reply = (client or _bedrock()).converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [
            {"image": {"format": fmt, "source": {"bytes": image}}},
            {"text": PROMPT},
        ]}],
        inferenceConfig={"temperature": 0, "maxTokens": 300},
    )
    text = "".join(b.get("text", "") for b in reply["output"]["message"]["content"])
    return parse(text)


def parse(text: str) -> dict:
    """The model's answer, checked rather than trusted."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"found": False, "unsure": "the label could not be read"}
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return {"found": False, "unsure": "the label could not be read"}
    if not data.get("found"):
        return {"found": False, "unsure": data.get("unsure") or "no brand and model number were readable"}
    brand = str(data.get("brand") or "").strip()
    if brand.isupper() and len(brand) > 3:
        brand = brand.title()  # "BOSCH" as printed on the plate reads as "Bosch"
    model = str(data.get("model_number") or "").strip().upper()
    kind = str(data.get("kind") or "").strip().lower()
    if not brand or not MODEL_SHAPE.match(model):
        return {"found": False, "unsure": f"'{model or 'nothing'}' does not look like a model number"}
    return {"found": True, "kind": kind or "appliance", "brand": brand, "model_number": model,
            "serial_number": str(data.get("serial_number") or "").strip(), "unsure": str(data.get("unsure") or "").strip()}


def recall_check(appliance: dict, fetch=recalls.fetch_recalls) -> dict:
    """The live CPSC check for one appliance. A failure is reported, not hidden."""
    try:
        found = recalls.match_recalls(appliance, fetch(appliance["category"]))
    except Exception as exc:  # noqa: BLE001 - the person is told the check did not run
        return {"checked": False, "error": type(exc).__name__}
    return {"checked": True, "matches": found}


def decode_upload(body: bytes, content_type: str) -> tuple[bytes, str]:
    """The image from a request: raw bytes, or a data: URL from the browser."""
    if content_type.startswith("text/plain") or body[:5] == b"data:":
        header, _, payload = body.decode().partition(",")
        media = header.removeprefix("data:").split(";")[0]
        return base64.b64decode(payload), media
    return body, content_type.split(";")[0].strip()
