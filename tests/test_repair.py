from datetime import date

import pytest

from home_operator import store

TODAY = date(2026, 9, 17)

FURNACE_REPAIR = "58sta-clean-air-filter"


@pytest.fixture
def home():
    return store.load_home()


def start_furnace(home):
    return store.start_repair(home, "furnace", "clean or replace the air filter", TODAY)


def nav(home, action, step, repair=FURNACE_REPAIR, said=""):
    return store.navigate_repair(home, action, repair, step, TODAY, said)


# What a person actually says to confirm a machine is safe.
CONFIRMED = "it's off and unplugged"


def test_diagnose_ranks_causes_and_offers_a_fix(home):
    result = store.diagnose_symptom(home, "furnace", "the airflow is weak", TODAY)
    assert result["found"] is True
    top = result["causes"][0]
    assert top["likelihood"] == "most likely"
    assert top["fix_available"] is True
    assert top["procedure_id"] == FURNACE_REPAIR
    assert top["days_since_last_done"] is not None


@pytest.mark.parametrize("spoken", [
    "Why won't my furnace blow properly?",
    "the airflow is weak!",
    "There's hardly any air from the vents.",
])
def test_diagnose_handles_punctuation_and_apostrophes(home, spoken):
    """All three mean weak airflow, which the manual blames on a dirty filter."""
    result = store.diagnose_symptom(home, "furnace", spoken, TODAY)
    assert result["found"] is True
    assert result["symptom"] == "there is not enough airflow from the vents"
    assert result["causes"][0]["procedure_id"] == FURNACE_REPAIR


def test_find_appliance_ignores_punctuation(home):
    assert [a["id"] for a in store.find_appliances(home, "the fridge!")] == ["fridge-1"]


def test_diagnose_unknown_symptom_lists_what_is_known(home):
    result = store.diagnose_symptom(home, "furnace", "it is playing music", TODAY)
    assert result["found"] is False
    assert result["known_symptoms"]


def test_start_repair_returns_first_step_with_safety(home):
    result = start_furnace(home)
    assert result["started"] is True
    assert result["step_number"] == 1 and result["total_steps"] == 9
    assert result["tools_needed"] and result["safety_note"]
    # The caller is told which repair this is, so it can navigate without the
    # server remembering anything.
    assert result["repair"] == FURNACE_REPAIR


def test_gate_step_blocks_until_confirmed(home):
    started = start_furnace(home)
    assert started["awaiting_confirmation"] is True
    assert "off" in started["confirm_prompt"]

    blocked = nav(home, "next", step=1)
    assert blocked["step_number"] == 1
    assert blocked["awaiting_confirmation"] is True


def test_confirming_the_gate_advances(home):
    after = nav(home, "done", step=1, said=CONFIRMED)
    assert after["step_number"] == 2
    assert after["awaiting_confirmation"] is False


def test_going_back_to_a_gate_asks_again(home):
    """Returning to a power-off step re-asks, because time has passed and the
    machine may have been plugged back in. Safer than remembering a yes."""
    back = nav(home, "back", step=2)
    assert back["step_number"] == 1
    assert back["awaiting_confirmation"] is True


def test_procedure_without_a_gate_advances_normally(home):
    started = store.start_repair(home, "washer", "clean the door seal", TODAY)
    assert started["awaiting_confirmation"] is False
    moved = store.navigate_repair(home, "next", started["repair"], 1, TODAY)
    assert moved["step_number"] == 2


def test_repeat_holds_position_so_a_question_mid_repair_does_not_lose_your_place(home):
    assert nav(home, "repeat", step=3)["step_number"] == 3
    assert nav(home, "repeat", step=3)["step_number"] == 3


def test_back_stops_at_the_first_step(home):
    assert nav(home, "back", step=2)["step_number"] == 1
    assert nav(home, "back", step=1)["step_number"] == 1


def test_finishing_the_last_step_logs_the_service(home):
    before = len(home["service_log"])
    result = nav(home, "next", step=9)

    assert result["finished"] is True
    assert result["logged"]["task"] == "clean or replace the air filter"
    assert result["logged"]["next_due"] == "2026-10-15"
    assert len(home["service_log"]) == before + 1


def test_navigating_without_naming_a_repair_explains_instead_of_failing(home):
    result = store.navigate_repair(home, "next", "", 1, TODAY)
    assert result["active"] is False
    assert result["available_repairs"]


def test_a_repair_survives_a_server_that_remembers_nothing(home):
    """The reason this tool takes a step number.

    On AgentCore Runtime a second call can land on a different copy of the
    container, which never saw the repair start. Here that is simulated by
    loading a fresh home - no shared state of any kind - and carrying on.
    """
    started = start_furnace(home)
    elsewhere = store.load_home()
    resumed = store.navigate_repair(
        elsewhere, "done", started["repair"], started["step_number"], TODAY, CONFIRMED
    )
    assert resumed["step_number"] == 2
    assert resumed["procedure"] == started["procedure"]


def test_two_repairs_interleave_without_interfering(home):
    furnace = start_furnace(home)
    washer = store.start_repair(home, "washer", "clean the door seal", TODAY)

    a = store.navigate_repair(home, "done", furnace["repair"], 1, TODAY, CONFIRMED)
    b = store.navigate_repair(home, "next", washer["repair"], 1, TODAY)

    assert a["procedure"] == furnace["procedure"] and a["step_number"] == 2
    assert b["procedure"] == washer["procedure"] and b["step_number"] == 2


def test_a_spoken_task_name_works_as_well_as_the_id(home):
    """A model relaying a conversation may paraphrase rather than pass the id."""
    result = store.navigate_repair(home, "done", "clean the furnace air filter", 1, TODAY, CONFIRMED)
    assert result["repair"] == FURNACE_REPAIR
    assert result["step_number"] == 2


@pytest.mark.parametrize("bad_step", [0, -3, 99, None, "two"])
def test_a_nonsense_step_number_lands_somewhere_valid(home, bad_step):
    result = nav(home, "repeat", step=bad_step)
    assert 1 <= result["step_number"] <= result["total_steps"]


def test_unknown_action_keeps_the_current_step(home):
    result = nav(home, "sideways", step=1)
    assert result["step_number"] == 1
    assert result["valid_actions"] == ["next", "back", "repeat", "done"]


def test_log_service_clears_the_overdue_item(home):
    filter_task = "clean or replace the air filter"
    overdue = store.maintenance_due(home, TODAY)["overdue"]
    assert any(i["nickname"] == "Furnace" and i["task"] == filter_task for i in overdue)
    others = {(i["nickname"], i["task"]) for i in overdue}

    logged = store.log_service(home, "furnace", filter_task, TODAY, notes="MERV 11")
    assert logged["next_due"] == "2026-10-15"   # every 4 weeks, page 6

    after = store.maintenance_due(home, TODAY)["overdue"]
    assert not any(i["nickname"] == "Furnace" and i["task"] == filter_task for i in after)
    # Everything else the furnace needs is still due: one job, one clock.
    assert others - {(i["nickname"], i["task"]) for i in after} == {("Furnace", filter_task)}
