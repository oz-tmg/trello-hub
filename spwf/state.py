"""Pure transition guards; event parsing and list resolution are separate work.

The caller must resolve the card's labels and current list before using this
policy. A None target is a strict no-op, including comments and due-date writes.
"""

from dataclasses import dataclass
from enum import Enum


class State(str, Enum):
    DOING = "doing"
    BLOCKED = "blocked"
    REVIEW = "review"
    DONE = "done"


@dataclass(frozen=True)
class Transition:
    target: State | None
    reason: str
    complete_due: bool = False


def plan_transition(
    target: State,
    *,
    current: State | None,
    is_experiment: bool = False,
    is_reference: bool = False,
    ci_failed: bool = False,
    has_due: bool = False,
) -> Transition:
    """Guard a requested move without performing network or filesystem I/O.

    ``current=None`` represents another board list. ``is_reference`` identifies
    Program & Gates cards. ``ci_failed`` distinguishes automatic CI failures from
    an explicit blocked trailer, which may move a card out of Review.
    """
    if is_reference:
        return Transition(None, "reference card: moves forbidden")
    if ci_failed and target == State.BLOCKED and current == State.REVIEW:
        return Transition(None, "CI failure does not move cards out of review")
    reason = "requested transition"
    if is_experiment and target == State.DONE:
        target = State.REVIEW
        reason = "experiment: human read required"
    if current == target:
        return Transition(None, "already in target list")
    return Transition(target, reason, complete_due=has_due and target == State.DONE)
