# Trello Hub

Scaffold for `savepoint-workflow`, a small, board-agnostic Python package named
`spwf`. GitHub events will update Trello cards using consumer configuration.

This package currently validates configuration and plans transitions offline.
It performs no Trello requests and does not yet synchronize GitHub events.
The project currently lives in `trello-hub`;
the GitHub repository is [oz-tmg/trello-hub](https://github.com/oz-tmg/trello-hub).

## Local development

Requires Python 3.11 or later.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/spwf --version
.venv/bin/python -m spwf --help
```

GitHub CI runs the same test suite and entrypoint checks on Python 3.11 and 3.13.
The repository uses the MIT license in `LICENSE`.

## Documentation

`AGENTS.md` and `CLAUDE.md` contain shared standing instructions. Private design
and board conventions live in a separate context repository. Link them locally:

```sh
./load-context.sh /absolute/path/to/private/context/directory
```

The directory must contain `PROJECT_CONTEXT.md` and `TRELLO_WORKFLOW.md`.
Both links are gitignored. The loader refuses to overwrite existing files or
links pointing elsewhere. Read order: agent guidance, project context, board
conventions, then this README. Public clones can install and test without the
private documents; contract-dependent development requires those documents.

## Implemented

- Installable package and CLI help/version entrypoints.
- Pure transition policy with no I/O: Experiment completion redirects to Review;
  reference cards cannot move; repeated moves do nothing; CI failures preserve
  Review; only Done completes an existing due date.
- Table-driven policy tests and development CI.
- A consumer configuration template in `workflow.example.yaml`; supply your board
  identifier before use.
- Strict Pydantic configuration with safe YAML loading, unknown/duplicate-key
  rejection and sanitized errors. PyYAML handles YAML syntax.
- GitHub push, PR and completed CI failure parsing, including branch/body/trailer
  bindings, squash merges and a pure helper for PR precedence within a batch.

The policy expects resolved card facts. It does not yet resolve live list IDs or
enforce ordering across separate workflow runs.

## Offline interfaces and event rules

```python
from spwf.config import load_config
from spwf.github import parse_event

config = load_config("workflow.yaml")
requests = parse_event("push", event_payload, config)
```

`event_payload` is a decoded GitHub event JSON object. These functions do no
network I/O; requests must pass `spwf.state.plan_transition` with current card
facts before any execution is implemented.

- Only the configured consumer prefix binds a branch. A branch's creation push
  requests Doing; later branch-only pushes do nothing.
- Exact `Trello: <shortlink> <keyword>` lines supply explicit commands. A branch
  and trailer naming different cards cause an error. On unbound branches,
  trailers may name multiple cards. The latest commit command per card wins.
- `done` on a push is accepted only on `main` with `allow_done_from_push: true`.
  A disallowed explicit Done produces no fallback Doing move.
- PR opened requests Review; PR merged into `main` requests Done. Body trailers
  supply bindings; the PR lifecycle determines the requested state. Closing
  without merging and merges into other branches do nothing.
- Completed CI failures request Blocked. The transition guard preserves cards
  already in Review. Success, cancellation and skipped checks cause no move.
- `coalesce_requests` gives PR events precedence over pushes for the same card
  and SHA in a supplied batch. A future runner must obtain PR context across
  runs; a standalone push payload cannot establish that precedence.

`config.target_list(state)` returns a configured list name. For Done it requires
an explicit `month_label` suffix; the board's exact month naming must be verified
before adding automatic date formatting. `lists.reference` is optional and
defaults to `📌 Program & Gates`.

## Remaining Milestone 1 work

1. Confirm the exact current-month list naming and resolve list IDs at runtime.
2. Implement the Trello client with mocked response tests, safe errors and
   idempotent writes. A read-only live smoke test requires an API key/token.
3. Add `trello_sync.py` and reusable `trello-sync.yml` with dry-run mode,
   SHA/run-URL comments, cross-run PR precedence and the consumer failure policy.
4. Owner provisions `TRELLO_KEY` and `TRELLO_TOKEN` and chooses secret scope.
   Wire the first consumer and validate a real push.

The CLI currently exposes help and version only; configuration and event parsing
are Python interfaces. Actual list names must match the consumer's board exactly.
No reusable workflow or `v1` release is available yet.

Prefect hooks, calendars and the agent-facing server remain deferred until the
earlier milestones and two weeks of real use are complete.
