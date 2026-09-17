from datetime import date

import pytest

from home_operator import store

TODAY = date(2026, 9, 17)


@pytest.fixture
def home():
    return store.load_home()


@pytest.fixture
def sessions():
    return {}


def test_diagnose_ranks_causes_and_offers_a_fix(home):
    result = store.diagnose_symptom(home, "dishwasher", "it won't drain, there's standing water", TODAY)
    assert result["found"] is True
    top = result["causes"][0]
    assert top["likelihood"] == "most likely"
    assert top["fix_available"] is True
    assert top["procedure_id"] == "dw-clean-filter"
    assert top["days_since_last_done"] == 219


@pytest.mark.parametrize("spoken", [
    "Why won't my dishwasher drain?",
    "it wont drain!",
    "There's standing water in the bottom.",
])
def test_diagnose_handles_punctuation_and_apostrophes(home, spoken):
    result = store.diagnose_symptom(home, "dishwasher", spoken, TODAY)
    assert result["found"] is True
    assert result["causes"][0]["procedure_id"] == "dw-clean-filter"


def test_find_appliance_ignores_punctuation(home):
    assert [a["id"] for a in store.find_appliances(home, "the fridge!")] == ["fridge-1"]


def test_diagnose_unknown_symptom_lists_what_is_known(home):
    result = store.diagnose_symptom(home, "dishwasher", "it is playing music", TODAY)
    assert result["found"] is False
    assert result["known_symptoms"]


def test_start_repair_returns_first_step_with_safety(home, sessions):
    result = store.start_repair(home, sessions, "dishwasher", "clean the filter", TODAY)
    assert result["started"] is True
    assert result["step_number"] == 1 and result["total_steps"] == 7
    assert result["tools_needed"] and result["safety_note"]
    assert sessions["current"]["step_index"] == 0


def test_repeat_holds_position_so_a_question_mid_repair_does_not_lose_your_place(home, sessions):
    store.start_repair(home, sessions, "dishwasher", "clean the filter", TODAY)
    store.navigate_repair(home, sessions, "next", TODAY)
    store.navigate_repair(home, sessions, "next", TODAY)
    assert store.navigate_repair(home, sessions, "repeat", TODAY)["step_number"] == 3
    assert store.navigate_repair(home, sessions, "repeat", TODAY)["step_number"] == 3


def test_back_stops_at_the_first_step(home, sessions):
    store.start_repair(home, sessions, "dishwasher", "clean the filter", TODAY)
    store.navigate_repair(home, sessions, "next", TODAY)
    assert store.navigate_repair(home, sessions, "back", TODAY)["step_number"] == 1
    assert store.navigate_repair(home, sessions, "back", TODAY)["step_number"] == 1


def test_finishing_the_last_step_logs_the_service(home, sessions):
    before = len(home["service_log"])
    store.start_repair(home, sessions, "dishwasher", "clean the filter", TODAY)
    for _ in range(6):
        store.navigate_repair(home, sessions, "next", TODAY)
    result = store.navigate_repair(home, sessions, "next", TODAY)

    assert result["finished"] is True
    assert result["logged"]["task"] == "clean the filter"
    assert result["logged"]["next_due"] == "2026-12-16"
    assert len(home["service_log"]) == before + 1
    assert "current" not in sessions


def test_navigating_with_no_repair_in_progress_explains_instead_of_failing(home, sessions):
    result = store.navigate_repair(home, sessions, "next", TODAY)
    assert result["active"] is False
    assert result["available_repairs"]


def test_unknown_action_keeps_the_current_step(home, sessions):
    store.start_repair(home, sessions, "dishwasher", "clean the filter", TODAY)
    result = store.navigate_repair(home, sessions, "sideways", TODAY)
    assert result["step_number"] == 1
    assert result["valid_actions"] == ["next", "back", "repeat"]


def test_log_service_clears_the_overdue_item(home):
    overdue = store.maintenance_due(home, TODAY)["overdue"]
    assert any(i["nickname"] == "Furnace" for i in overdue)

    logged = store.log_service(home, "furnace", "replace the air filter", TODAY, notes="MERV 11")
    assert logged["next_due"] == "2026-12-16"

    after = store.maintenance_due(home, TODAY)["overdue"]
    assert not any(i["nickname"] == "Furnace" for i in after)
