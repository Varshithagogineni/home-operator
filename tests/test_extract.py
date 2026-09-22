import json

import pytest

from home_operator import extract

GOOD = {
    "consumables": [{"name": "detergent", "part_number": None, "size": "HE only"}],
    "maintenance": [{"task": "clean the drain pump filter", "interval_days": 30}],
    "symptoms": [{
        "symptom": "shows error code OE",
        "keywords": ["oe", "error", "code", "drain"],
        "causes": [
            {"cause": "The drain pump filter is clogged.", "short": "the drain pump filter",
             "likelihood": "most likely", "procedure_id": "clean-drain-pump-filter"},
            {"cause": "The drain hose is kinked.", "short": "a kinked drain hose",
             "likelihood": "possible", "procedure_id": "does-not-exist"},
        ],
    }],
    "procedures": [{
        "id": "clean-drain-pump-filter", "title": "Clean the drain pump filter",
        "task": "clean the drain pump filter", "minutes": 15,
        "tools_needed": ["a shallow pan", "a towel"],
        "safety_note": "Unplug the washer before cleaning the filter.",
        "gate_prompt": "Tell me when the washer is unplugged.",
        "steps": ["Unplug the washer.", "Open the drain pump filter cover.", "Drain the water, then remove the filter."],
    }],
}


class FakeBedrock:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {"output": {"message": {"content": [{"text": self.text}]}},
                "usage": {"inputTokens": 1200, "outputTokens": 300}}


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "manual.pdf"
    path.write_bytes(b"%PDF-1.4 fake manual")
    return path


def test_sends_the_pdf_to_nova_with_a_neutral_name(pdf):
    bedrock = FakeBedrock(json.dumps(GOOD))
    extraction, usage = extract.extract(pdf, "LG", "WM9500HKA", "washing machine", client=bedrock)
    call = bedrock.calls[0]
    assert call["modelId"] == "us.amazon.nova-2-lite-v1:0"
    doc = call["messages"][0]["content"][0]["document"]
    assert doc["format"] == "pdf" and doc["name"] == "manual" and doc["source"]["bytes"].startswith(b"%PDF")
    assert "WM9500HKA" in call["messages"][0]["content"][1]["text"]
    assert usage["input_tokens"] == 1200 and usage["output_tokens"] == 300
    assert extraction.procedures[0].gate_prompt


def test_tasks_without_a_stated_frequency_are_dropped_and_minutes_may_be_unknown():
    payload = {**GOOD,
               "maintenance": [{"task": "clean the oven", "interval_days": None},
                               {"task": "clean the drain pump filter", "interval_days": 30}],
               "procedures": [{**GOOD["procedures"][0], "minutes": None}]}
    extraction = extract.parse_response(json.dumps(payload))
    assert [m.task for m in extraction.maintenance] == ["clean the drain pump filter"]
    assert extraction.procedures[0].minutes is None


def test_markdown_fences_around_the_json_are_tolerated():
    extraction = extract.parse_response("```json\n" + json.dumps(GOOD) + "\n```")
    assert extraction.symptoms[0].keywords[0] == "oe"


def test_causes_pointing_at_missing_procedures_are_unlinked():
    extraction = extract.parse_response(json.dumps(GOOD))
    causes = extraction.symptoms[0].causes
    assert causes[0].procedure_id == "clean-drain-pump-filter"
    assert causes[1].procedure_id is None


@pytest.mark.parametrize("bad", [
    "Sorry, I can't read that manual.",
    json.dumps({**GOOD, "procedures": [{**GOOD["procedures"][0], "steps": ["only one step"]}]}),
    json.dumps({**GOOD, "maintenance": [{"task": "clean it", "interval_days": -5}]}),
])
def test_malformed_output_stops_with_a_clear_error(bad):
    with pytest.raises(extract.ExtractionError, match="expected format"):
        extract.parse_response(bad)


def test_oversized_manual_is_refused_before_calling_aws(tmp_path):
    big = tmp_path / "big.pdf"
    big.write_bytes(b"0" * (extract.MAX_PDF_BYTES + 1))
    bedrock = FakeBedrock(json.dumps(GOOD))
    with pytest.raises(extract.ExtractionError, match="S3"):
        extract.extract(big, "LG", "X", "washer", client=bedrock)
    assert bedrock.calls == []
