"""The Nova 2 Sonic relay's guard: the text path's safety rules, applied to a
speech model that calls tools on its own. No AWS needed; nothing here streams."""

from home_operator.sonic import Guard, coverage, speak_line

REPAIR = "wm9500hka-clean-the-drain-pump-filter"
GATE = "Tell me when the washer is off and unplugged."


def started():
    return {"started": True, "repair": REPAIR, "step_number": 1, "total_steps": 8,
            "step": "Turn off the washer, and unplug the power cord.",
            "awaiting_confirmation": True, "confirm_prompt": GATE,
            "say_first": "Opening the drain filter will result in water overflowing. " + GATE}


def at_step(n, gate=False):
    return {"active": True, "finished": False, "repair": REPAIR, "step_number": n,
            "total_steps": 8, "step": f"Step text {n}.",
            **({"awaiting_confirmation": True, "confirm_prompt": GATE} if gate else {})}


def test_the_persons_own_words_replace_the_models_version():
    g = Guard()
    g.heard("yes, walk me through it")
    g.observe("start_repair", started())
    g.heard("next")
    args, blocked = g.prepare("navigate_repair", {"action": "done", "said": "the washer is unplugged"})
    assert blocked is None
    assert args["said"] == "next"


def test_repair_and_step_come_from_the_last_reply_not_the_model():
    g = Guard()
    g.heard("walk me through it")
    g.observe("start_repair", started())
    g.heard("its unplugged")
    g.observe("navigate_repair", at_step(2))
    g.heard("next")
    args, _ = g.prepare("navigate_repair", {"action": "next", "repair": "made-up", "step": 7})
    assert args["repair"] == REPAIR
    assert args["step"] == 2


def test_a_repair_cannot_start_in_the_same_breath_as_its_diagnosis():
    g = Guard()
    g.heard("my washer won't drain")
    g.observe("diagnose_symptom", {"found": True, "causes": []})
    _, blocked = g.prepare("start_repair", {"appliance": "washer", "task": "clean the filter"})
    assert blocked and blocked["blocked"]
    g.heard("yes please")
    _, blocked = g.prepare("start_repair", {"appliance": "washer", "task": "clean the filter"})
    assert blocked is None


def test_only_one_move_through_a_repair_per_thing_said():
    """Told "yes", Sonic started, cleared the gate and advanced in one breath,
    and the opening safety warning was never spoken."""
    g = Guard()
    g.heard("yes, walk me through it")
    g.observe("start_repair", started())
    g.last_speak = "the opening line"
    _, blocked = g.prepare("navigate_repair", {"action": "done"})
    assert blocked["blocked"]
    assert blocked["speak"] == "the opening line"
    g.heard("its unplugged")
    _, blocked = g.prepare("navigate_repair", {"action": "done"})
    assert blocked is None


def test_stop_puts_the_repair_down():
    g = Guard()
    g.heard("walk me through it")
    g.observe("start_repair", started())
    g.heard("never mind")
    assert g.repair is None and g.step is None


def test_finishing_clears_the_repair():
    g = Guard()
    g.heard("go")
    g.observe("start_repair", started())
    g.heard("next")
    g.observe("navigate_repair", {"finished": True, "repair": REPAIR, "message": "Done."})
    assert g.repair is None


def test_a_gate_that_holds_is_reported_as_held():
    g = Guard()
    g.heard("walk me through it")
    assert g.observe("start_repair", started()) is False
    g.heard("next")
    assert g.observe("navigate_repair", at_step(1, gate=True)) is True


def test_arriving_at_a_gate_is_not_a_hold():
    g = Guard()
    g.heard("walk me through it")
    g.observe("start_repair", {**started(), "awaiting_confirmation": False})
    g.heard("next")
    assert g.observe("navigate_repair", at_step(2, gate=True)) is False


def test_repeat_at_a_gate_reads_the_step_not_the_hold_line():
    g = Guard()
    g.heard("walk me through it")
    g.observe("start_repair", started())
    g.heard("say that again")
    assert g.observe("navigate_repair", at_step(1, gate=True)) is False


def test_speak_lines_quote_the_manual():
    assert speak_line("start_repair", started()) == started()["say_first"]
    assert speak_line("navigate_repair", at_step(3)) == "Step 3. Step text 3."
    assert speak_line("navigate_repair", at_step(3, gate=True)) == f"Step 3. Step text 3. {GATE}"
    assert speak_line("navigate_repair", at_step(1, gate=True), held=True) == f"Hold on, safety first. {GATE}"
    assert speak_line("get_appliance", {"found": True}) is None


def test_coverage_allows_friendly_words_but_not_rewording():
    line = "Step 2. Open the drain pump filter cover."
    assert coverage(line, "Good. Step 2. Open the drain pump filter cover.") == 1.0
    assert coverage(line, "Now open the drain filter cover") < 0.85


# -- narration, and going to a step by number ------------------------------------

import asyncio
from datetime import date

from home_operator import store
from home_operator.sonic import is_narration, requested_step, walk


def test_spoken_reasoning_is_caught():
    for leak in (
        "The user wants the filter, so I will call get appliance.",
        "Okay, calling the diagnose symptom tool.",
        "The tool response shows three items overdue.",
        "Let me call navigate_repair.",
    ):
        assert is_narration(leak), leak


def test_ordinary_speech_is_not_caught():
    for fine in (
        "It takes a sixteen by twenty-five filter.",
        "Tell me when the washer is off and unplugged.",
        "You'll want a towel and a flat tool.",
        "I can call someone for you.",
        "Step 2. Open the drain pump filter cover.",
    ):
        assert not is_narration(fine), fine


def test_steps_asked_for_by_number():
    assert requested_step("tell me step four", 8) == 4
    assert requested_step("go to step 3", 8) == 3
    assert requested_step("what's the fifth step", 8) == 5
    assert requested_step("skip to the final step", 8) == 8
    # "last step" already means "back" in chat.py; "next step" is not a number.
    assert requested_step("last step", 8) is None
    assert requested_step("next step", 8) is None


def _local_call():
    home = store.load_home()

    async def call(name, args):
        assert name == "navigate_repair"
        return store.navigate_repair(home, args["action"], args["repair"], args["step"], date.today(), args["said"])

    return call


def test_jumping_ahead_cannot_skip_a_power_off_gate():
    data, held = asyncio.run(walk(_local_call(), REPAIR, 1, 4, 8))
    assert held
    assert data["step_number"] == 1 and data["awaiting_confirmation"]


def test_jumping_ahead_past_a_cleared_gate_lands_on_the_step():
    data, held = asyncio.run(walk(_local_call(), REPAIR, 2, 5, 8))
    assert not held
    assert data["step_number"] == 5


def test_jumping_to_the_final_step_does_not_finish_the_repair():
    data, held = asyncio.run(walk(_local_call(), REPAIR, 2, 8, 8))
    assert data["step_number"] == 8 and not data.get("finished")


def test_jumping_back_to_the_gate_asks_again():
    data, held = asyncio.run(walk(_local_call(), REPAIR, 5, 1, 8))
    assert not held
    assert data["step_number"] == 1 and data["awaiting_confirmation"]


def test_a_step_named_by_the_person_becomes_a_jump():
    g = Guard()
    g.heard("walk me through it")
    g.observe("start_repair", started())
    g.heard("its unplugged")
    g.observe("navigate_repair", at_step(2))
    g.heard("tell me step five")
    assert g.jump_target("navigate_repair", {"action": "next"}) == 5
    g.heard("repeat")
    assert g.jump_target("navigate_repair", {"action": "repeat", "step": 2}) is None


def test_a_recall_warning_is_spoken_once_per_conversation():
    g = Guard()
    due = {"say_first": "Heads up, the dishwasher's model is named in a recall.", "overdue": []}
    first = g.once("get_maintenance_due", due)
    assert first["say_first"] == due["say_first"]
    again = g.once("get_appliance", {**due, "nickname": "Dishwasher"})
    assert "say_first" not in again and again["recall_already_mentioned"]
    assert due["say_first"]  # the tool's own data, which the card shows, is untouched


def test_a_repairs_opening_line_is_never_dropped():
    g = Guard()
    g.once("start_repair", started())
    assert g.once("start_repair", started())["say_first"] == started()["say_first"]


# -- speech versus the manuals' index ------------------------------------------

from home_operator.sonic import due_line, normalize_symptom, wrong_code


def _diagnose(appliance, heard):
    return store.diagnose_symptom(store.load_home(), appliance, normalize_symptom(heard), date.today())


def test_a_code_heard_as_letters_is_the_code_not_the_first_one_listed():
    """ "u e" used to score only on "error code" and come back as IE."""
    assert _diagnose("washer", "error code u e")["symptom"] == "shows error code UE"
    assert _diagnose("washer", "it's showing o e")["symptom"] == "shows error code OE"


def test_smells_finds_the_manuals_odor_entry():
    assert _diagnose("dishwasher", "it smells bad")["symptom"] == "odor"


def test_a_code_the_manual_does_not_have_is_not_answered_with_another():
    heard = "error code zz"
    assert wrong_code(heard, _diagnose("washer", heard)) == "zz"
    assert wrong_code("error code u e", _diagnose("washer", "error code u e")) is None
    assert wrong_code("won't drain", _diagnose("washer", "won't drain")) is None


def test_whats_due_is_one_sentence_about_the_worst():
    line = due_line({"overdue": [
        {"nickname": "Washer", "task": "replace the water hoses", "who": "homeowner"},
        {"nickname": "Furnace", "task": "clean or replace the air filter", "who": "homeowner"},
    ], "upcoming": []})
    assert line == "Two things are overdue. The most overdue is the washer: replace the water hoses."
    assert "Nothing's overdue" in due_line({"overdue": [], "upcoming": []})
