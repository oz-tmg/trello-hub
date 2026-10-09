from dataclasses import replace

import pytest

from spwf.github import EventError, coalesce_requests, parse_event
from spwf.state import State, plan_transition


def push(message="A change", *, branch="ws/AbCd1234-feature", created=False):
    commit = {"id": "a" * 40, "message": message}
    return {
        "ref": f"refs/heads/{branch}", "created": created, "deleted": False,
        "after": commit["id"], "head_commit": commit, "commits": [commit],
    }


def pr(*, action="opened", merged=False, base="main", branch="ws/AbCd1234-feature", body=None):
    return {"action": action, "pull_request": {
        "head": {"ref": branch, "sha": "a" * 40},
        "base": {"ref": base}, "body": body, "merged": merged,
        "merge_commit_sha": "b" * 40,
        "html_url": "https://github.com/example/project/pull/1",
    }}


def test_branch_only_first_push_starts_work(config):
    [request] = parse_event("push", push(created=True), config)
    assert request.card == "AbCd1234"
    assert request.target == State.DOING
    assert request.subject == "A change"
    assert request.branch == "ws/AbCd1234-feature"


def test_later_branch_push_does_not_regress_review(config):
    assert parse_event("push", push(), config) == []


@pytest.mark.parametrize("message,target,reason", [
    ("Change\n\nTrello: AbCd1234 doing", State.DOING, ""),
    ("Change\n\nTrello: AbCd1234 blocked: awaiting access", State.BLOCKED, "awaiting access"),
    ("Change\n\nTrello: AbCd1234 review", State.REVIEW, ""),
    ("Squash PR (#2)\n\nTrello: AbCd1234 done", State.DONE, ""),
])
def test_trailer_only_and_squash_merge(config, message, target, reason):
    [request] = parse_event("push", push(message, branch="main"), config)
    assert (request.card, request.target, request.reason) == ("AbCd1234", target, reason)


def test_explicit_trailer_overrides_first_push(config):
    [request] = parse_event("push", push("Trello: AbCd1234 review", created=True), config)
    assert request.target == State.REVIEW


def test_no_binding_is_noop(config):
    assert parse_event("push", push(branch="feature/unbound", created=True), config) == []
    assert parse_event("pull_request", pr(branch="feature/unbound"), config) == []


@pytest.mark.parametrize("branch", [
    "WS/AbCd1234-feature", "ig/AbCd1234-feature", "ws/AbCd123-feature",
    "ws/AbCd12345-feature", "ws/AbCd1234-", "ws/AbCd1234-bad slug",
])
def test_branch_binding_requires_configured_prefix_and_valid_shortlink(config, branch):
    assert parse_event("push", push(branch=branch, created=True), config) == []


@pytest.mark.parametrize("event,payload", [
    ("push", push("Trello: ZzYy9876 review")),
    ("pull_request", pr(body="Trello: ZzYy9876 review")),
])
def test_disagreeing_branch_and_trailer_are_rejected(config, event, payload):
    with pytest.raises(EventError, match="different cards"):
        parse_event(event, payload, config)


@pytest.mark.parametrize("message", [
    "Trello: AbCd1234 blocked:", "Trello: AbCd1234 nonsense",
    "Trello: toolong123 review", "Trello: AbCd1234 review\nTrello: AbCd1234 doing",
])
def test_bad_or_conflicting_trailers_rejected(config, message):
    with pytest.raises(EventError):
        parse_event("push", push(message), config)


def test_prose_is_not_a_trailer(config):
    assert parse_event("push", push("Example Trello: AbCd1234 review"), config) == []


@pytest.mark.parametrize("created", [False, True])
def test_done_on_feature_branch_is_ignored_without_fallback(config, created):
    assert parse_event("push", push("Trello: AbCd1234 done", created=created), config) == []


def test_push_completion_can_be_disabled(config):
    config = config.model_copy(update={"allow_done_from_push": False})
    assert parse_event("push", push("Trello: AbCd1234 done", branch="main"), config) == []
    assert parse_event("pull_request", pr(action="closed", merged=True), config)[0].target == State.DONE


def test_last_commit_command_wins_and_multiple_cards_are_supported(config):
    payload = push("Trello: AbCd1234 review\nTrello: ZzYy9876 doing", branch="main")
    payload["commits"].insert(0, {"id": "c" * 40, "message": "Trello: AbCd1234 doing"})
    requests = parse_event("push", payload, config)
    assert [(r.card, r.target) for r in requests] == [
        ("AbCd1234", State.REVIEW), ("ZzYy9876", State.DOING),
    ]


def test_head_commit_is_used_if_commit_array_absent(config):
    payload = push("Trello: AbCd1234 review")
    del payload["commits"]
    assert parse_event("push", payload, config)[0].target == State.REVIEW


def test_deleted_branches_and_tags_are_ignored(config):
    payload = push("Trello: AbCd1234 review")
    payload["deleted"] = True
    assert parse_event("push", payload, config) == []
    payload["deleted"] = False
    payload["ref"] = "refs/tags/v1"
    assert parse_event("push", payload, config) == []


@pytest.mark.parametrize("body,branch", [
    (None, "ws/AbCd1234-feature"),
    ("Trello: AbCd1234 doing", "ws/AbCd1234-feature"),
    ("Trello: AbCd1234 review", "feature/unbound"),
])
def test_opened_pr_reaches_review_with_branch_or_body_binding(config, body, branch):
    [request] = parse_event("pull_request", pr(body=body, branch=branch), config)
    assert request.target == State.REVIEW
    assert request.url.endswith("/pull/1")


def test_merged_pr_uses_merge_sha(config):
    [request] = parse_event("pull_request", pr(action="closed", merged=True), config)
    assert request.target == State.DONE
    assert request.sha == "b" * 40


@pytest.mark.parametrize("payload", [
    pr(action="closed"), pr(action="closed", merged=True, base="release"),
    pr(action="synchronize"),
])
def test_non_actionable_pr_events_are_noops(config, payload):
    assert parse_event("pull_request", payload, config) == []


@pytest.mark.parametrize("reverse", [False, True])
def test_pr_precedence_on_same_card_and_commit_is_independent_of_order(config, reverse):
    pushed = parse_event("push", push(created=True), config)
    opened = parse_event("pull_request", pr(), config)
    candidates = pushed + opened
    if reverse:
        candidates.reverse()
    assert coalesce_requests(candidates) == opened
    other = replace(pushed[0], sha="c" * 40)
    assert len(coalesce_requests([*opened, other])) == 2


@pytest.mark.parametrize("event", ["workflow_run", "check_run", "check_suite"])
def test_ci_failure_to_blocked_preserves_review_through_policy(config, event):
    check = {"conclusion": "failure", "head_sha": "a" * 40}
    branch = "ws/AbCd1234-feature"
    if event == "check_run":
        check["check_suite"] = {"head_branch": branch}
    else:
        check["head_branch"] = branch
    payload = {
        "action": "completed", event: check,
        "repository": {"html_url": "https://github.com/example/project"},
    }
    [request] = parse_event(event, payload, config)
    assert request.ci_failed
    assert request.url.endswith("/checks")
    assert plan_transition(request.target, current=State.REVIEW, ci_failed=request.ci_failed).target is None
    assert plan_transition(request.target, current=State.DOING, ci_failed=request.ci_failed).target == State.BLOCKED


@pytest.mark.parametrize("conclusion", ["success", "neutral", "cancelled", "skipped", None])
def test_non_failure_checks_do_nothing(config, conclusion):
    payload = {"action": "completed", "workflow_run": {"conclusion": conclusion}}
    assert parse_event("workflow_run", payload, config) == []


def test_unfinished_or_unknown_events_do_nothing(config):
    assert parse_event("workflow_run", {"action": "requested"}, config) == []
    assert parse_event("issues", {}, config) == []


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_malformed_active_events_produce_safe_errors(config, event):
    payload = {"action": "opened", "ref": 123, "secret": "DO-NOT-PRINT"}
    with pytest.raises(EventError) as error:
        parse_event(event, payload, config)
    assert "DO-NOT-PRINT" not in str(error.value)


def test_merged_experiment_is_redirected_before_list_mapping(config):
    [request] = parse_event("pull_request", pr(action="closed", merged=True), config)
    decision = plan_transition(request.target, current=State.DOING, is_experiment=True)
    assert config.target_list(decision.target) == "Review"
