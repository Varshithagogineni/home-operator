"""The recall sentence is safety-critical, so its wording is pinned by tests.

A CPSC recall lists model numbers. Whether one particular appliance is affected
depends on its serial number, which only its owner can read off the label. So
the only honest thing to say is that the model is named and may be affected.
Saying "your dishwasher is recalled", or telling someone to stop using a working
appliance, would both be wrong.
"""

from datetime import date

import pytest

from home_operator import store

TODAY = date(2026, 9, 23)

# Wording that must never appear: each of these overstates what is known.
FORBIDDEN = [
    "is recalled",
    "has been recalled",
    "is part of a safety recall",
    "stop using",
    "do not use",
]


@pytest.fixture
def home():
    return store.load_home()


def test_the_recalled_model_gets_a_say_first_line(home):
    result = store.describe_appliance(home, "dishwasher", TODAY)
    assert result["open_recalls"], "the Bosch dishwasher should match a real CPSC recall"
    assert "say_first" in result


def test_an_appliance_with_no_recall_has_no_say_first(home):
    assert "say_first" not in store.describe_appliance(home, "washer", TODAY)


def test_maintenance_due_leads_with_the_recall(home):
    assert store.maintenance_due(home, TODAY)["say_first"].startswith("Before anything else")


def test_the_sentence_says_may_be_affected_and_names_the_check(home):
    line = store.describe_appliance(home, "dishwasher", TODAY)["say_first"]
    assert "named in a safety recall" in line
    assert "may be affected" in line
    assert "serial number" in line


@pytest.mark.parametrize("phrase", FORBIDDEN)
def test_the_sentence_never_overstates_the_risk(home, phrase):
    line = store.describe_appliance(home, "dishwasher", TODAY)["say_first"].lower()
    assert phrase not in line


def test_the_hazard_from_the_recall_notice_is_included(home):
    line = store.describe_appliance(home, "dishwasher", TODAY)["say_first"]
    assert "overheat" in line and "catch fire" in line


def test_a_recall_with_no_hazard_text_still_reads_as_a_sentence():
    line = store.recall_sentence("Dryer", {"hazard": "", "url": None})
    assert line.startswith("Before anything else")
    assert "serial number" in line
    assert "  " not in line


def test_the_agent_is_told_to_speak_it_verbatim():
    from home_operator import agent

    # The prompt is wrapped for readability, so compare on a single line.
    prompt = " ".join(agent.SYSTEM_PROMPT.split())
    assert "say_first" in prompt
    assert "word for word" in prompt
    assert "Never say an appliance \"is recalled\"" in prompt
