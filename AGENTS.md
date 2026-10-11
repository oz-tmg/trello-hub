# Agent guidance

Read this file, then `PROJECT_CONTEXT.md`, then `TRELLO_WORKFLOW.md`, then
`README.md`. The two private context files are ignored symlinks. Run
`./load-context.sh /absolute/path/to/private/context/directory` to restore them.
If unavailable, stop work that depends on private contracts and report the gap.

The local folder is `trello-hub`; the design calls the project
`savepoint-workflow` and the Python distribution/import `spwf`. Preserve `spwf`
until the owner changes that decision. The GitHub remote is
`https://github.com/oz-tmg/trello-hub`.

Keep this file and `CLAUDE.md` identical. Standing instructions go here;
decisions, history and integration contracts go in the private context file.
For meaningful changes, append a dated update there using its update protocol.

## Scope and invariants

- Build Milestone 1 first: package, state machine, GitHub event parser, Trello
  client, reusable workflow, then the first consumer.
- Prefect, calendars and an MCP server remain gated on later milestones.
- Trello is the hub. GitHub writes to Trello; calendars eventually read Trello.
- Experiment cards never reach Done through automation; redirect to Review.
- Program & Gates cards never move. An already-correct list means no writes.
- CI failures must not move cards out of Review.
- Keep consumer board/list data in configuration. Keep API credentials out of
  source, config, exceptions and logs; never enable shell tracing with secrets.
- Future synchronization failures must not fail the consumer's CI. Package
  development CI must still fail on broken tests.
- Keep private context, personal board details, research data and methodology
  out of tracked files. Do not force-add ignored files.
- Dry-run must remain entirely offline; fixture state is forbidden in live mode.
- Run only the pinned automation package in reusable workflows, never consumer PR code.
- Query current same-repository PR state before live push moves. Skip fork PRs.
- Trello writes are not automatically retried; report partial move/comment failures.
- Stop and report blockers. Live validation requires credentials; publishing,
  pushing and owner decisions remain human checkpoints in the project workflow.

## Development

Python 3.11+, `requests` for HTTP, `pydantic` for configuration, `pytest` for
tests. Keep policy pure and cover guards and event rules with table-driven
tests. Do not add frameworks or future integrations preemptively.

Install: `python3 -m venv .venv`, then
`.venv/bin/python -m pip install -e '.[dev]'`.
Validate: `.venv/bin/python -m pytest` and `.venv/bin/spwf --version`.
