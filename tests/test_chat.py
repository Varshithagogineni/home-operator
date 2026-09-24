"""The routing decision: does a phrase go to the model, or straight to a tool?

Only the pure parts are tested here. Anything that opens a session to AgentCore
needs AWS credentials, so it is exercised by hand and in the demo, not in CI.
"""

import pytest

from home_operator.chat import _first_json, fast_action


@pytest.mark.parametrize("said, action", [
    ("next", "next"),
    ("Next.", "next"),
    ("ok, next", "next"),
    ("okay next", "next"),
    ("continue", "next"),
    ("carry on", "next"),
    ("got it", "next"),
    ("back", "back"),
    ("go back", "back"),
    ("previous", "back"),
    ("one step back", "back"),
    ("repeat", "repeat"),
    ("say that again", "repeat"),
    ("what was that", "repeat"),
    ("one more time", "repeat"),
    ("done", "done"),
    ("it's off", "done"),
    ("its unplugged", "done"),
    ("unplugged", "done"),
    ("i unplugged it", "done"),
    ("power is off", "done"),
])
def test_navigation_words_skip_the_model(said, action):
    assert fast_action(said) == action


@pytest.mark.parametrize("said", [
    "my washer won't drain",
    "is the dishwasher safe?",
    "what filter does the fridge take",
    "anything due in the house",
    "i need a technician",
    "next week i'll replace the hoses",   # "next" but not a navigation command
    "go back to what you said about the recall",
    "done with the laundry, what about the oven",
])
def test_everything_else_goes_to_the_model(said):
    """A phrase only takes the fast path if that is all it could mean.

    "next week I'll replace the hoses" starts with "next" but is not navigation,
    so the anchored patterns require a word boundary and nothing else after it
    that changes the meaning.
    """
    assert fast_action(said) is None


def test_a_filler_word_does_not_hide_a_command():
    assert fast_action("um, next") == "next"
    assert fast_action("alright repeat") == "repeat"


def test_tool_results_parse_from_a_dict():
    """Strands hands back a dict."""
    assert _first_json({"content": [{"text": '{"step_number": 3}'}]}) == {"step_number": 3}


def test_tool_results_parse_from_objects():
    """The MCP SDK hands back objects."""

    class Block:
        text = '{"step_number": 4}'

    class Result:
        content = [Block()]

    assert _first_json(Result()) == {"step_number": 4}


def test_non_json_text_is_ignored_rather_than_raising():
    assert _first_json({"content": [{"text": "not json"}]}) is None
    assert _first_json({"content": []}) is None
    assert _first_json({}) is None
