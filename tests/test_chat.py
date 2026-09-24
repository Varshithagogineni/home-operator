"""The routing decision: does a phrase go to the model, or straight to a tool?

Only the pure parts are tested here. Anything that opens a session to AgentCore
needs AWS credentials, so it is exercised by hand and in the demo, not in CI.
"""

import json

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


class FakeAgent:
    """Just enough of a Strands agent to test what the backend does with a turn."""

    def __init__(self, messages):
        self.messages = messages

    def __call__(self, said):
        return "a sentence the model made up"


def _turn(*pairs):
    """Build the message list a turn produces: (tool name, args, result) each."""
    messages = []
    for i, (name, args, result) in enumerate(pairs):
        use_id = f"t{i}"
        messages.append({"content": [{"toolUse": {"toolUseId": use_id, "name": name, "input": args}}]})
        messages.append({"content": [{"toolResult": {"toolUseId": use_id,
                                                     "content": [{"text": json.dumps(result)}]}}]})
    return messages


def test_each_call_keeps_its_own_result():
    from home_operator.chat import _exchange

    calls = _exchange(FakeAgent(_turn(
        ("diagnose_symptom", {"appliance": "washer"}, {"found": True, "symptom": "OE"}),
        ("start_repair", {"task": "filter"}, {"started": True, "repair": "r1"}),
    )), 0)
    assert [c["name"] for c in calls] == ["diagnose_symptom", "start_repair"]
    assert calls[0]["result"]["symptom"] == "OE"
    assert calls[1]["result"]["repair"] == "r1"


def test_results_are_matched_by_id_not_by_order():
    """Tool results can come back interleaved, so they are matched on id."""
    from home_operator.chat import _exchange

    messages = [
        {"content": [{"toolUse": {"toolUseId": "a", "name": "get_appliance", "input": {}}},
                     {"toolUse": {"toolUseId": "b", "name": "diagnose_symptom", "input": {}}}]},
        {"content": [{"toolResult": {"toolUseId": "b", "content": [{"text": '{"who": "b"}'}]}},
                     {"toolResult": {"toolUseId": "a", "content": [{"text": '{"who": "a"}'}]}}]},
    ]
    calls = _exchange(FakeAgent(messages), 0)
    assert {c["name"]: c["result"]["who"] for c in calls} == {
        "get_appliance": "a", "diagnose_symptom": "b"
    }


# --- Saying yes to an offered repair -----------------------------------------
#
# Asked "want me to walk you through it?", a person says "yes please". The model
# answered that turn with no tool call at all and recited a repair step from its
# own memory. So the acceptance is recognised here and answered by start_repair.

@pytest.mark.parametrize("said", [
    "yes", "yes please", "yeah", "yep", "sure", "ok", "okay", "please do",
    "go ahead", "do it", "walk me through it", "show me", "talk me through it",
])
def test_an_acceptance_is_recognised(said):
    from home_operator.chat import is_acceptance
    assert is_acceptance(said)


@pytest.mark.parametrize("said", [
    "no thanks",
    "not now",
    "yes but first what's the part number",
    "my washer won't drain",
    "what does it cost",
    "yes i replaced the hoses last year",
])
def test_anything_less_than_a_plain_yes_goes_to_the_model(said):
    from home_operator.chat import is_acceptance
    assert not is_acceptance(said)


def test_an_acceptance_is_not_a_gate_confirmation():
    """Two different yeses. Agreeing to a repair must never clear a power-off
    gate: that is the bug that sent someone to open a live machine."""
    from home_operator.chat import fast_action, is_acceptance

    assert is_acceptance("yes please")
    assert fast_action("yes please") is None


def test_a_repair_step_is_never_spoken_without_a_tool_call(monkeypatch):
    """The rule that matters most.

    Twice, mid-repair, the model answered with no tool call and recited a step
    from memory - once as "open the drain filter cover", which is not the
    wording in the manual. During a repair those turns are discarded and the
    current step is read again from the server.
    """
    from home_operator import chat as conversations

    talk = object.__new__(conversations.Conversation)
    talk.repair = "wm9500hka-clean-the-drain-pump-filter"
    talk.step = 1
    talk.offer = None
    talk.last_used = 0.0
    talk.agent = FakeAgent([{"content": [{"text": "Now open the drain filter cover."}]}])

    repeated = {}

    def fake_fast(action, said):
        repeated["action"] = action
        return {"path": "fast", "say": None, "tool_calls": [], "data": {"step_number": 1}}

    talk._fast = fake_fast
    monkeypatch.setattr(conversations, "_exchange", lambda agent, i: [])

    reply = talk._ask_agent("yes it is")

    assert repeated["action"] == "repeat", "it should re-read the step from the server"
    assert reply["say"] is None, "the model's own sentence must not be spoken"
    assert reply["overridden"]


def test_the_model_does_not_narrate_repair_steps(monkeypatch):
    """Even when it calls the right tool, it does not get to phrase the step.

    It called navigate_repair, was told the washer still had to be unplugged,
    and then said "Now open the drain filter cover" anyway - wording that is not
    in the manual. Any turn touching a repair tool is spoken by the step card,
    from the tool's own text.
    """
    from home_operator import chat as conversations

    talk = object.__new__(conversations.Conversation)
    talk.repair = None
    talk.step = None
    talk.offer = None
    talk.last_used = 0.0
    talk.agent = FakeAgent([])

    monkeypatch.setattr(conversations, "_exchange", lambda agent, i: [
        {"name": "navigate_repair", "args": {"action": "done"},
         "result": {"step_number": 1, "awaiting_confirmation": True, "repair": "r1"}}
    ])

    reply = talk._ask_agent("yes it is")
    assert reply["say"] is None
    assert reply["data"]["awaiting_confirmation"] is True


def test_the_model_still_speaks_for_everything_else(monkeypatch):
    """Outside a repair its own words are the point - that is the warmth."""
    from home_operator import chat as conversations

    talk = object.__new__(conversations.Conversation)
    talk.repair = None
    talk.step = None
    talk.offer = None
    talk.last_used = 0.0
    talk.agent = FakeAgent([])

    monkeypatch.setattr(conversations, "_exchange", lambda agent, i: [
        {"name": "get_maintenance_due", "args": {}, "result": {"overdue": []}}
    ])

    reply = talk._ask_agent("anything due?")
    assert reply["say"] == "a sentence the model made up"


# --- Getting out of a repair -------------------------------------------------
#
# A demo got stuck: a repair was open at a safety gate, the next question was
# routed into navigate_repair, and the gate answered with the same sentence
# every time. There was no way out except saying the machine was unplugged.

@pytest.mark.parametrize("said", [
    "stop", "cancel", "quit", "never mind", "nevermind", "forget it",
    "leave it", "start over", "not now", "later",
])
def test_a_repair_can_be_put_down(said):
    from home_operator.chat import is_escape
    assert is_escape(said)


@pytest.mark.parametrize("said", [
    "next", "it's unplugged", "my washer is showing OE", "stop the machine first",
    "what needs doing",
])
def test_ordinary_talk_is_not_an_escape(said):
    from home_operator.chat import is_escape
    assert not is_escape(said)


def test_leaving_a_repair_clears_the_place():
    from home_operator import chat as conversations

    talk = object.__new__(conversations.Conversation)
    talk.repair, talk.step, talk.offer = "r1", 3, {"appliance": "Washer"}
    reply = talk.leave_repair()

    assert talk.repair is None and talk.step is None and talk.offer is None
    assert "leave that for now" in reply["say"]
    assert reply["tool_calls"] == []
