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


def test_a_gated_repair_dictates_its_opening_line(home):
    """The warning, the first step and the gate question, in full sentences."""
    started = store.start_repair(home, "washer", "clean the drain pump filter", TODAY)
    line = started["say_first"]
    assert line.startswith("Opening the drain filter will result in water overflowing")
    assert "Turn off the washer, and unplug the power cord." in line
    assert line.endswith("Tell me when the washer is off and unplugged.")


def test_the_opening_line_ends_its_sentences(home):
    """A model once ran a warning into a step: "open the drain filter will cause
    water to overflow". Every part is punctuated so that cannot happen."""
    for task in ("clean the drain pump filter", "clean the door seal"):
        line = store.start_repair(home, "washer", task, TODAY)["say_first"]
        assert line.strip().endswith((".", "?", "!"))
        assert ".." not in line


def test_a_repair_with_no_safety_note_still_opens_cleanly():
    line = store._opening_line({"safety_note": None, "steps": ["Pull the filter out"], "gate_step": None})
    assert line == "Pull the filter out."


# --- A safety gate clears on what the person said, not on being asked to ------
#
# The model, given a vague "yes please", called navigate_repair with
# action="done" and cleared the power-off gate on the washer repair. That sent
# someone to open a drain filter on a machine that may still have been plugged
# in and full of water. Asking the model not to do that is not a control, so the
# tool refuses instead.

WASHER_REPAIR = "wm9500hka-clean-the-drain-pump-filter"


def test_done_without_the_persons_words_does_not_clear_a_gate(home):
    held = store.navigate_repair(home, "done", WASHER_REPAIR, 1, TODAY)
    assert held["step_number"] == 1
    assert held["awaiting_confirmation"] is True


@pytest.mark.parametrize("vague", ["yes", "yes please", "sure", "ok", "go ahead", "", "   "])
def test_a_vague_yes_is_not_a_confirmation(home, vague):
    """Agreeing to a repair is not the same as saying the power is off."""
    held = store.navigate_repair(home, "done", WASHER_REPAIR, 1, TODAY, vague)
    assert held["step_number"] == 1, f"{vague!r} should not clear a safety gate"
    assert held["awaiting_confirmation"] is True


@pytest.mark.parametrize("confirmation", [
    "it's unplugged",
    "its off",
    "the power is off",
    "I unplugged it",
    "done, it's off",
    "unplugged",
])
def test_the_persons_own_words_do_clear_it(home, confirmation):
    moved = store.navigate_repair(home, "done", WASHER_REPAIR, 1, TODAY, confirmation)
    assert moved["step_number"] == 2
    assert moved["awaiting_confirmation"] is False


def test_words_are_only_needed_at_a_gate(home):
    """Ordinary steps are not gates, so "done" moves on without ceremony."""
    moved = store.navigate_repair(home, "done", WASHER_REPAIR, 3, TODAY)
    assert moved["step_number"] == 4
