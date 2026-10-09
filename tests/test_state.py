import pytest

from spwf.state import State, plan_transition


@pytest.mark.parametrize("target", State)
def test_reference_cards_never_move(target):
    result = plan_transition(target, current=None, is_reference=True, has_due=True)
    assert result.target is None
    assert not result.complete_due


@pytest.mark.parametrize("target", State)
def test_same_list_is_strict_noop(target):
    result = plan_transition(target, current=target, has_due=True)
    assert result.target is None
    assert not result.complete_due


@pytest.mark.parametrize("current", [None, *State])
def test_experiments_never_reach_done(current):
    result = plan_transition(
        State.DONE, current=current, is_experiment=True, has_due=True
    )
    assert result.target == (None if current == State.REVIEW else State.REVIEW)
    assert not result.complete_due
    if result.target:
        assert result.reason == "experiment: human read required"


@pytest.mark.parametrize("has_due", [False, True])
def test_regular_done_completes_only_existing_due_date(has_due):
    result = plan_transition(State.DONE, current=State.REVIEW, has_due=has_due)
    assert result.target == State.DONE
    assert result.complete_due == has_due


def test_ci_failure_preserves_review_but_explicit_block_does_not():
    assert plan_transition(
        State.BLOCKED, current=State.REVIEW, ci_failed=True
    ).target is None
    assert plan_transition(State.BLOCKED, current=State.REVIEW).target == State.BLOCKED


def test_ci_failure_blocks_active_work():
    assert plan_transition(
        State.BLOCKED, current=State.DOING, ci_failed=True
    ).target == State.BLOCKED


@pytest.mark.parametrize("target", [State.DOING, State.BLOCKED, State.REVIEW])
def test_intermediate_moves_never_complete_due_dates(target):
    result = plan_transition(target, current=None, has_due=True)
    assert result.target == target
    assert not result.complete_due
