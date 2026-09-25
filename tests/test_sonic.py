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
