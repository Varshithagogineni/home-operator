"""Turn a manufacturer's PDF manual into Home Operator data, using Amazon Bedrock.

Slow-lane work: one Bedrock call per manual, run ahead of time, never during a
tool call. A person reviews the output before it goes into the home data.
"""
import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

MODEL_ID = "us.amazon.nova-2-lite-v1:0"
REGION = "us-east-1"
# Bedrock's limit for a document sent inline; larger manuals need S3.
MAX_PDF_BYTES = 4_500_000
EXTRACTED_DIR = Path(__file__).parent / "data" / "extracted"

PROMPT = """You are reading the owner's manual for a {brand} {category}, model {model}.
Extract what a voice assistant needs to help the owner maintain and repair it.
Use ONLY information stated in the manual. Do not invent part numbers, intervals or steps.

Return ONLY a JSON object, with no markdown and no commentary, in exactly this shape:
{{
  "consumables": [{{"name": "...", "part_number": "... or null", "size": "... or null"}}],
  "maintenance": [{{"task": "short verb phrase, e.g. clean the drain pump filter", "interval_days": 30}}],
  "symptoms": [{{
    "symptom": "short description, e.g. will not drain",
    "meaning": "for an error code, what the manual says it means in plain words, e.g. water can't drain; otherwise null",
    "source_page": 44,
    "keywords": ["lowercase words a person might say"],
    "causes": [{{
      "cause": "one sentence",
      "short": "2-5 word noun phrase, e.g. the drain pump filter",
      "likelihood": "most likely | possible | less likely",
      "procedure_id": "id of a procedure below, or null"
    }}]
  }}],
  "procedures": [{{
    "id": "kebab-case-id",
    "source_page": 40,
    "title": "e.g. Clean the drain pump filter",
    "task": "same verb phrase as the matching maintenance task, if any",
    "minutes": 10,
    "tools_needed": ["only items the manual names, such as a bucket; otherwise empty"],
    "safety_note": "one sentence from the manual's warnings",
    "gate_prompt": "if step 1 is about power, water or heat: a question asking the person to confirm it is safe, e.g. Tell me when the washer is unplugged. Otherwise null",
    "steps": ["one action per step, written to be spoken aloud, under 25 words"]
  }}]
}}

Rules:
- For every error code in the manual, add a symptom such as "shows error code OE", and put the code in lowercase in its keywords (e.g. "oe"), plus words like "error", "code", "display".
- Order causes from most to least likely.
- Only add a maintenance task when the manual states a specific frequency ("monthly" = 30, "once a week" = 7, "every five years" = 1825).
  If it says only "periodically", "regularly" or "as needed", leave that task OUT of maintenance entirely. Never guess a number.
- source_page is the page number printed on the manual page where the information appears.
- Include every maintenance or troubleshooting procedure that has numbered or step-by-step instructions."""


class Consumable(BaseModel):
    name: str
    part_number: str | None = None
    size: str | None = None


class Maintenance(BaseModel):
    task: str
    interval_days: int = Field(gt=0)


class Cause(BaseModel):
    cause: str
    short: str
    likelihood: Literal["most likely", "possible", "less likely"]
    procedure_id: str | None = None


class Symptom(BaseModel):
    symptom: str
    meaning: str | None = None
    source_page: int | None = None
    keywords: list[str]
    causes: list[Cause] = Field(min_length=1)


class Procedure(BaseModel):
    id: str
    source_page: int | None = None
    title: str
    task: str
    minutes: int = Field(gt=0)
    tools_needed: list[str]
    safety_note: str
    gate_prompt: str | None = None
    steps: list[str] = Field(min_length=2)


class Extraction(BaseModel):
    consumables: list[Consumable]
    maintenance: list[Maintenance]
    symptoms: list[Symptom]
    procedures: list[Procedure]


class ExtractionError(Exception):
    pass


def parse_response(text: str) -> Extraction:
    """Validate the model's JSON. Models sometimes wrap it in ``` fences; strip those."""
    body = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        extraction = Extraction.model_validate(json.loads(body))
    except (json.JSONDecodeError, ValidationError) as e:
        raise ExtractionError(f"Bedrock returned data that doesn't match the expected format: {e}") from e

    known = {p.id for p in extraction.procedures}
    for symptom in extraction.symptoms:
        for cause in symptom.causes:
            if cause.procedure_id not in known:
                cause.procedure_id = None
    return extraction


def extract(pdf_path: Path, brand: str, model: str, category: str, client=None) -> tuple[Extraction, dict]:
    pdf = pdf_path.read_bytes()
    if len(pdf) > MAX_PDF_BYTES:
        raise ExtractionError(
            f"{pdf_path.name} is {len(pdf) / 1e6:.1f} MB; Bedrock accepts up to 4.5 MB inline. "
            "Larger manuals need to go through Amazon S3."
        )
    if client is None:
        import boto3
        client = boto3.client("bedrock-runtime", region_name=REGION)

    response = client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [
            # A neutral name: Bedrock warns the document name can act as a prompt injection.
            {"document": {"format": "pdf", "name": "manual", "source": {"bytes": pdf}}},
            {"text": PROMPT.format(brand=brand, category=category, model=model)},
        ]}],
        inferenceConfig={"maxTokens": 8000, "temperature": 0},
    )
    text = next(block["text"] for block in response["output"]["message"]["content"] if "text" in block)
    usage = response.get("usage", {})
    return parse_response(text), {"input_tokens": usage.get("inputTokens"), "output_tokens": usage.get("outputTokens")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract repair data from a PDF manual with Amazon Bedrock.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--brand", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--category", required=True, help='e.g. "washing machine"')
    args = parser.parse_args()

    extraction, usage = extract(args.pdf, args.brand, args.model, args.category)
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    out = EXTRACTED_DIR / f"{args.model.upper()}.raw.json"
    out.write_text(json.dumps({
        "source": {"manual": args.pdf.name, "model_id": MODEL_ID, "extracted_on": date.today().isoformat(), **usage},
        "brand": args.brand, "model_number": args.model.upper(), "category": args.category,
        **extraction.model_dump(),
    }, indent=2) + "\n")

    print(f"Saved {out}")
    print(f"  {len(extraction.consumables)} parts, {len(extraction.maintenance)} maintenance tasks, "
          f"{len(extraction.symptoms)} symptoms/error codes, {len(extraction.procedures)} procedures")
    print(f"  tokens in/out: {usage['input_tokens']} / {usage['output_tokens']}")
    print(f"Review it against the manual, then save the corrected version as {args.model.upper()}.json.")


if __name__ == "__main__":
    main()
