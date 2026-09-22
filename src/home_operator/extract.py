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
STRONGER_MODEL_ID = "us.amazon.nova-pro-v1:0"  # for manuals Nova 2 Lite reads too thinly
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
  "//": "leave a maintenance task out entirely if the manual gives no frequency; use null for minutes if no duration is stated",
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
    "safety_note": "one sentence from the manual's warnings for this task, or null if it gives none",
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
  Many manuals print the same content twice, in English and then in another language:
  always read and cite the ENGLISH pages.
- A procedure is a task with at least two sequential steps. If the manual's fix is a single action
  ("replace the fuse", "call a plumber", "close the door firmly"), do NOT make it a procedure:
  say it in the cause instead. Troubleshooting tables are mostly single actions; treat them as causes.
- Be exhaustive about procedures. Work through the whole manual, especially its care and maintenance
  section, and include EVERY task written as numbered or step-by-step instructions: cleaning routines,
  self-cleaning cycles, removing and refitting parts, replacing filters or lamps, and descaling.
  Most manuals contain between three and eight such procedures. Do not stop after the first one."""


class Consumable(BaseModel):
    name: str
    part_number: str | None = None
    size: str | None = None


class Maintenance(BaseModel):
    task: str
    # null when the manual gives no frequency; those entries are dropped below.
    interval_days: int | None = Field(default=None, gt=0)


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
    causes: list[Cause]


class Procedure(BaseModel):
    id: str
    source_page: int | None = None
    title: str
    task: str
    minutes: int | None = Field(default=None, gt=0)  # manuals often don't say how long a job takes
    tools_needed: list[str]
    safety_note: str | None = None  # plenty of procedures carry no warning
    gate_prompt: str | None = None
    steps: list[str]  # entries with fewer than two are dropped below


class Extraction(BaseModel):
    consumables: list[Consumable]
    maintenance: list[Maintenance]
    symptoms: list[Symptom]
    procedures: list[Procedure]


class ExtractionError(Exception):
    pass


def parse_response(text: str) -> Extraction:
    """Validate the model's JSON, keeping the usable entries.

    Models return the odd half-filled entry: a maintenance task with no interval, a symptom
    with no causes, a procedure with no steps. Those are dropped rather than failing the run,
    since the rest of a 50-page manual is still worth having. Malformed JSON still fails.
    """
    body = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        extraction = Extraction.model_validate(json.loads(body))
    except (json.JSONDecodeError, ValidationError) as e:
        raise ExtractionError(f"Bedrock returned data that doesn't match the expected format: {e}") from e

    extraction.maintenance = [m for m in extraction.maintenance if m.interval_days]
    extraction.procedures = [p for p in extraction.procedures if len(p.steps) >= 2]
    extraction.symptoms = [s for s in extraction.symptoms if s.causes]
    known = {p.id for p in extraction.procedures}
    for symptom in extraction.symptoms:
        for cause in symptom.causes:
            if cause.procedure_id not in known:
                cause.procedure_id = None
    return extraction


def upload_manual(pdf_path: Path, bucket: str, client=None) -> str:
    """Put the manual in S3 and return its s3:// address."""
    if client is None:
        import boto3
        client = boto3.client("s3", region_name=REGION)
    key = f"manuals/{pdf_path.name}"
    client.upload_file(str(pdf_path), bucket, key)
    return f"s3://{bucket}/{key}"


def extract(pdf_path: Path, brand: str, model: str, category: str, client=None,
            model_id: str = MODEL_ID, s3_uri: str | None = None) -> tuple[Extraction, dict]:
    if s3_uri:
        source = {"s3Location": {"uri": s3_uri}}
    else:
        pdf = pdf_path.read_bytes()
        if len(pdf) > MAX_PDF_BYTES:
            raise ExtractionError(
                f"{pdf_path.name} is {len(pdf) / 1e6:.1f} MB; Bedrock accepts up to 4.5 MB inline. "
                "Pass --s3-bucket to send it through Amazon S3 instead."
            )
        source = {"bytes": pdf}
    if client is None:
        import boto3
        from botocore.config import Config
        client = boto3.client("bedrock-runtime", region_name=REGION,
                              config=Config(read_timeout=900, retries={"max_attempts": 2}))

    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [
            # A neutral name: Bedrock warns the document name can act as a prompt injection.
            {"document": {"format": "pdf", "name": "manual", "source": source}},
            {"text": PROMPT.format(brand=brand, category=category, model=model)},
        ]}],
        # Manuals with long troubleshooting tables need room; a truncated reply is unusable JSON.
        inferenceConfig={"maxTokens": 20000, "temperature": 0},
    )
    text = next((block["text"] for block in response["output"]["message"]["content"] if "text" in block), "")
    try:
        parsed = parse_response(text)
    except ExtractionError as e:
        # Keep what came back, so the failure can be read rather than guessed at.
        EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
        failed = EXTRACTED_DIR / f"{model.upper()}.failed.txt"
        failed.write_text(text or "<empty response>")
        raise ExtractionError(f"{e} (reply saved at {failed})") from None
    usage = response.get("usage", {})
    return parsed, {"model_id": model_id, "source_uri": s3_uri or pdf_path.name,
                    "input_tokens": usage.get("inputTokens"), "output_tokens": usage.get("outputTokens")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract repair data from a PDF manual with Amazon Bedrock.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--brand", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--category", required=True, help='e.g. "washing machine"')
    parser.add_argument("--s3-bucket", help="upload the manual here first; needed for manuals over 4.5 MB")
    parser.add_argument("--stronger", action="store_true",
                        help="use Amazon Nova Pro, for manuals Nova 2 Lite reads too thinly")
    args = parser.parse_args()

    s3_uri = None
    if args.s3_bucket:
        s3_uri = upload_manual(args.pdf, args.s3_bucket)
        print(f"Uploaded to {s3_uri}")
    extraction, usage = extract(args.pdf, args.brand, args.model, args.category,
                                model_id=STRONGER_MODEL_ID if args.stronger else MODEL_ID, s3_uri=s3_uri)
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    out = EXTRACTED_DIR / f"{args.model.upper()}.raw.json"
    out.write_text(json.dumps({
        "source": {"manual": args.pdf.name, "extracted_on": date.today().isoformat(), **usage},
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
