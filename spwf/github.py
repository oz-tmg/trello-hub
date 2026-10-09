"""Pure GitHub event parsing. This module never fetches data or moves cards.

Payload reference: https://docs.github.com/en/webhooks/webhook-events-and-payloads
Inputs must be authenticated by the eventual workflow/runner before live use.
"""

import re
from dataclasses import dataclass
from typing import Any, Iterable

from spwf.config import WorkflowConfig
from spwf.state import State

_SHORTLINK = r"[A-Za-z0-9]{8}"
_TRAILER = re.compile(
    rf"^Trello: (?P<card>{_SHORTLINK}) (?:(?P<state>doing|review|done)|"
    r"blocked: (?P<reason>\S[^\r\n]*))$"
)
_FAILURES = {"failure", "timed_out", "action_required", "startup_failure"}


class EventError(ValueError):
    """A safe-to-log payload error; never include the raw event."""


@dataclass(frozen=True)
class Request:
    card: str
    target: State
    source: str
    sha: str
    branch: str
    subject: str = ""
    reason: str = ""
    url: str = ""
    ci_failed: bool = False


def _branch_card(branch: str, prefix: str) -> str | None:
    match = re.fullmatch(rf"{re.escape(prefix)}/({_SHORTLINK})-[^\s]+", branch)
    return match.group(1) if match else None


def _trailers(message: str) -> dict[str, tuple[State, str]]:
    """Read exact trailer lines; prose containing a Trello reference is ignored.

    Multiple cards are supported on an unbound branch. Conflicting commands for
    the same card within one message are rejected; later commits may supersede
    earlier commits. Lines beginning with Trello: must have valid syntax.
    """
    result = {}
    for line in message.splitlines():
        line = line.rstrip()
        if not line.startswith("Trello:"):
            continue
        match = _TRAILER.fullmatch(line)
        if not match:
            raise EventError("Malformed Trello trailer")
        card = match["card"]
        value = (State(match["state"] or "blocked"), match["reason"] or "")
        if card in result and result[card] != value:
            raise EventError("Conflicting Trello trailers for one card")
        result[card] = value
    return result


def _bindings(branch: str, message: str, config: WorkflowConfig):
    card = _branch_card(branch, config.prefix)
    trailers = _trailers(message)
    if card and any(other != card for other in trailers):
        raise EventError("Branch and trailer refer to different cards")
    return card, trailers


def parse_event(
    event: str, payload: dict[str, Any], config: WorkflowConfig
) -> list[Request]:
    """Parse supported payloads; unsupported/non-actionable events are no-ops.

    Missing mandatory fields and malformed active payloads are rejected with a
    safe error. The returned requests still need transition guards and current
    card facts before execution.
    """
    try:
        if event == "push":
            return _push(payload, config)
        if event == "pull_request":
            return _pull_request(payload, config)
        if event in {"workflow_run", "check_run", "check_suite"}:
            return _failure(event, payload, config)
        return []
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        if isinstance(exc, EventError):
            raise
        raise EventError("Malformed GitHub event payload") from None


def _push(payload, config):
    if payload.get("deleted") is True:
        return []
    ref = payload["ref"]
    if not ref.startswith("refs/heads/"):
        return []
    branch = ref.removeprefix("refs/heads/")
    branch_card = _branch_card(branch, config.prefix)
    head = payload.get("head_commit")
    commits = list(payload.get("commits") or [])
    if head and not any(commit["id"] == head["id"] for commit in commits):
        commits.append(head)
    requests: dict[str, Request] = {}
    if branch_card and payload.get("created") is True:
        message = (head or {}).get("message", "")
        requests[branch_card] = Request(
            branch_card, State.DOING, "push", payload["after"], branch,
            subject=message.splitlines()[0] if message else "",
        )
    for commit in commits:
        message = commit["message"]
        _, trailers = _bindings(branch, message, config)
        for card, (target, reason) in trailers.items():
            # Explicit but disallowed Done must not fall back to implicit Doing.
            if target == State.DONE and (branch != "main" or not config.allow_done_from_push):
                requests.pop(card, None)
                continue
            requests[card] = Request(
                card, target, "push", commit["id"], branch,
                subject=message.splitlines()[0] if message else "",
                reason=reason,
            )
    return list(requests.values())


def _pull_request(payload, config):
    action = payload.get("action")
    if action not in {"opened", "closed"}:
        return []
    pr = payload["pull_request"]
    if action == "closed":
        if pr.get("merged") is not True or pr["base"]["ref"] != "main":
            return []
        target = State.DONE
        sha = pr["merge_commit_sha"]
    else:
        target = State.REVIEW
        sha = pr["head"]["sha"]
    if not isinstance(sha, str) or not sha:
        raise EventError("Pull request is missing its relevant commit SHA")
    branch = pr["head"]["ref"]
    card, trailers = _bindings(branch, pr.get("body") or "", config)
    # The PR lifecycle determines the state; body trailers supply bindings.
    cards = list(trailers) or ([card] if card else [])
    return [
        Request(card, target, "pull_request", sha, branch, url=pr["html_url"])
        for card in cards
    ]


def _failure(event, payload, config):
    if payload.get("action") != "completed":
        return []
    check = payload[event]
    if check.get("conclusion") not in _FAILURES:
        return []
    suite = check.get("check_suite") or check
    branch = suite["head_branch"]
    if branch is None:
        return []
    card = _branch_card(branch, config.prefix)
    if not card:
        return []
    url = check.get("html_url") or (
        payload["repository"]["html_url"] + "/commit/" + check["head_sha"] + "/checks"
    )
    return [Request(
        card, State.BLOCKED, event, check["head_sha"], branch,
        reason="CI failed", url=url, ci_failed=True,
    )]


def coalesce_requests(requests: Iterable[Request]) -> list[Request]:
    """Give PR requests precedence over pushes for the same card and SHA.

    This resolves a supplied batch only. Cross-run ordering needs persisted or
    queried PR context in the future runner; a push payload cannot provide it.
    Within a source, the last supplied request wins.
    """
    result: dict[tuple[str, str], Request] = {}
    for request in requests:
        key = (request.card, request.sha)
        previous = result.get(key)
        if previous and previous.source == "pull_request" and request.source == "push":
            continue
        result[key] = request
    return list(result.values())
