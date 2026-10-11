"""Shared planning for fixture previews and live Trello synchronization."""

from dataclasses import asdict, dataclass
from datetime import datetime

from spwf.config import WorkflowConfig
from spwf.github import Request
from spwf.state import State, plan_transition
from spwf.trello import Board, Card, List, TrelloError


@dataclass(frozen=True)
class Plan:
    card: str
    target_id: str | None
    target_name: str | None
    reason: str
    comment: str = ""
    complete_due: bool = False


def list_id(lists: list[List], name: str) -> str:
    matches = [item.id for item in lists if item.name == name and not item.closed]
    if len(matches) != 1:
        raise TrelloError("Configured list is missing or ambiguous")
    return matches[0]


def plan(request: Request, card: Card, board: Board, lists: list[List],
         config: WorkflowConfig, *, run_url: str = "", now: datetime | None = None) -> Plan:
    if board.closed or card.closed or card.idBoard != board.id or card.shortLink != request.card:
        raise TrelloError("Card or board is archived, mismatched or outside the configured board")
    reference_id = list_id(lists, config.lists.reference)
    states = {state: list_id(lists, config.target_list(state))
              for state in (State.DOING, State.BLOCKED, State.REVIEW)}
    if len(set([reference_id, *states.values()])) != 4:
        raise TrelloError("Workflow list IDs overlap")
    current = next((state for state, ident in states.items() if ident == card.idList), None)
    decision = plan_transition(
        request.target, current=current,
        is_reference=card.idList == reference_id,
        is_experiment=config.experiment_label in {label.name for label in card.labels},
        has_due=card.due is not None, ci_failed=request.ci_failed,
    )
    if decision.target is None:
        return Plan(card.shortLink, None, None, decision.reason)
    name = config.target_list(decision.target, month_label=(
        config.current_month(now) if decision.target == State.DONE else None
    ))
    target = list_id(lists, name)
    if target == reference_id or (decision.target == State.DONE and target in states.values()):
        raise TrelloError("Done resolves to another workflow stage")
    if card.idList == target:
        return Plan(card.shortLink, None, None, "already in target list")
    lines = [f"spwf: {request.source}", f"Branch: {request.branch}", f"SHA: {request.sha}"]
    for label, value in [("Subject", request.subject), ("Reason", request.reason),
                         ("Source", request.url), ("Run", run_url)]:
        if value:
            lines.append(f"{label}: {value}")
    if decision.reason == "experiment: human read required":
        lines.append(decision.reason)
    return Plan(card.shortLink, target, name, decision.reason, "\n".join(lines), decision.complete_due)


def synchronize(requests, client, config, *, run_url="", now=None):
    """Live only. Strict no-op means no comment or due-date write either.

    A move and due completion use one PUT. Comments follow successful moves.
    A comment failure is reported, never blindly retried (writes aren't atomic).
    """
    results = []
    for request in requests:
        card = client.get_card(request.card)
        move = plan(request, card, client.board(), client.lists(), config, run_url=run_url, now=now)
        if move.target_id is None:
            results.append({**asdict(move), "status": "noop"})
            continue
        if client.move(card, move.target_id, complete_due=move.complete_due):
            try:
                client.comment(card.shortLink, move.comment)
            except TrelloError:
                raise TrelloError("Card moved but comment failed; inspect card before retrying") from None
            results.append({**asdict(move), "status": "moved"})
    return results
