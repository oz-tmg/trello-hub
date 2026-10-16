# Trello Hub

`spwf` turns GitHub events into guarded Trello card transitions. The repository
is [oz-tmg/trello-hub](https://github.com/oz-tmg/trello-hub); its original design
name was `savepoint-workflow`. Python 3.11+; MIT licensed.

The client, runner, reusable workflow and offline tests are implemented.
**WingspanAI is active; dedicated-card live validation passed on 2026-10-15.**
The two-week ordinary-use milestone remains outstanding. No `v1` release has
been created. Prefect hooks, calendar writers and an MCP server remain gated
on later milestones.

## Try it without credentials

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/spwf sync --config examples/workflow.yaml \
  --event-name push --event-path examples/push.json \
  --snapshot examples/snapshot.json --dry-run
```

This synthetic example plans a move to Doing and prints the intended comment.
Dry-run performs **zero network calls**, even if credentials are present. Without
`--snapshot`, it prints unverified event intent rather than claiming a final move:
card labels, list membership and live PR precedence cannot be checked offline.
Fixture snapshots are rejected in live mode.

## Behavior

- The configured branch prefix binds a card (`ws/<8-character-shortlink>-slug`).
  Only the creation push requests Doing automatically.
- Exact `Trello: <shortlink> doing`, `blocked: <reason>`, `review` or `done` lines
  in commit messages supply explicit commands. Conflicting branch/card bindings
  are rejected; latest commit command per card wins.
- Push completion requires `main` and `allow_done_from_push: true`.
- PR opened requests Review; merged into `main` requests Done. Body trailers
  provide bindings; the PR lifecycle determines the requested state.
- Live runs query current PR state. Associated PRs override push requests for the
  same card/commit. A delayed opened event after merge uses the current merged
  state. Closed/unmerged PRs suppress delayed push moves. Conflicting associated
  PR states or failed GitHub lookups stop the run before Trello writes.
- Completed CI failures request Blocked, preserving cards already in Review.
  Results for an older branch head are ignored. Success/cancellation do nothing.
- Experiment cards stop at Review. Program & Gates cards never move.
- Already in the target list means no writes, including no comments/due updates.
- Archived cards, foreign-board cards, missing/ambiguous lists and changes to
  card facts detected before a move prevent that move.
- Done completes an existing due date in the same PUT as the move. Comments
  include branch, SHA, subject/reason, PR or CI URL and the workflow run URL.

## Configure and connect a consumer

Follow [the consumer setup guide](docs/consumer-setup.md). It includes the
read-only smoke check, first live move and required GitHub permissions.

`workflow.example.yaml` lists the configuration fields. `done_month_format`
must match the board's actual current-month list (`%Y-%m`, `%B`, `%B %Y`, or `%b %Y`). It
has no default: missing configuration blocks ordinary Done moves, while
Experiment redirection still works. Dates use the configured timezone (default
America/Vancouver). Lists are resolved by exact name and cached per run; this
package does not create or rename them.

The reusable workflow defaults to dry-run. It accepts configuration through a
GitHub repository variable and installs the automation from an explicit full
commit SHA. It does not check out or execute consumer branch code. Fork PRs are
skipped. Pin the workflow and package to the same reviewed commit.

## Failure and concurrency boundaries

The CLI exits nonzero on errors unless `--soft-fail` is specified. The reusable
workflow uses that flag and a non-blocking job, so ordinary integration failures
are logged without failing consumer CI. This repository's development tests
still fail normally. Cancellation, invalid caller YAML and GitHub infrastructure
failures are outside the runner's control.

Runs are serialized per consumer repository with cancellation disabled. GitHub
concurrency may replace pending runs and does not promise FIFO ordering; the
current-state PR lookup handles replay ordering, but this is not a durable event
queue. Distinct cards lost from the pending queue may need a manual rerun. Do
not bind the same card from multiple consumer repositories: cross-repository
serialization is not implemented.

Trello does not provide an atomic transaction spanning move and comment here.
The client refetches card facts before moving, but a human edit can still race
after that read. No writes are automatically retried. A failed comment after a
successful move is reported explicitly; rerunning an already-moved card is a
strict no-op, so inspect the card and repair its audit comment manually. This
also applies to ambiguous network failures where a write may have succeeded.

Offline examples use synthetic fixtures, not recordings of the private board.
The first consumer's hosted live checks verified moves and audit comments,
replay no-ops, current PR precedence and Experiment completion protection.
Dedicated validation events do not count toward the ordinary-use milestone.
Fork behavior is covered offline; a hosted fork test remains outstanding.

## Development and private context

Read `AGENTS.md`, private `PROJECT_CONTEXT.md`, private `TRELLO_WORKFLOW.md`, then
this README. Restore the two ignored links with:

```sh
./load-context.sh /absolute/path/to/private/context/directory
```

Keep `AGENTS.md` and `CLAUDE.md` identical. Public clones can run all tests and the
offline demo without private docs or credentials. Tests forbid real HTTP calls.
CI tests Python 3.11 and 3.13.

Main modules: `spwf.config` (schema), `spwf.github` (pure event parsing),
`spwf.github_client` (current PR lookup), `spwf.state` (guards), `spwf.trello`
(REST operations), `spwf.sync` (planning/execution), and `spwf.cli` (commands).
`trello_sync.py` is a compatibility entrypoint for `spwf sync`.
