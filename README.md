# Trello Hub

Scaffold for `savepoint-workflow`, a small, board-agnostic Python package named
`spwf`. GitHub events will update Trello cards using consumer configuration.

This is an initial local scaffold. It performs no Trello requests and does not
yet synchronize GitHub events. The project currently lives in `trello-hub`;
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

The policy expects resolved card facts. It does not yet map events to requested
states, load YAML, resolve lists or enforce cross-event ordering.

## Remaining Milestone 1 work

1. Validate/load `workflow.yaml`; determine the YAML parser dependency and exact
   current-month list naming. Resolve list names at runtime.
2. Parse card bindings from branch names, commit trailers and PR bodies; cover
   first pushes, main-only completion, squash merges and PR precedence.
3. Implement the Trello client with mocked response tests, safe errors and
   idempotent writes. A read-only live smoke test requires an API key/token.
4. Add `trello_sync.py` and reusable `trello-sync.yml` with dry-run mode,
   SHA/run-URL comments and the consumer failure policy.
5. Owner provisions `TRELLO_KEY` and `TRELLO_TOKEN` and chooses secret scope. Wire the first consumer and validate a real push.

The supplied workflow example describes the planned contract; it is not loaded
by the CLI yet. Actual list names must match the consumer's board exactly.
No versioned reusable workflow is available yet.

Prefect hooks, calendars and the agent-facing server remain deferred until the
earlier milestones and two weeks of real use are complete.
