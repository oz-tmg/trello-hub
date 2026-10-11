# First consumer setup and validation

This guide prepares the first consumer (the `ws` prefix is supported). It does
not activate a consumer or require sharing credentials in a chat. The reusable
workflow has not yet been validated against the live board.

## 1. Review and pin the automation

Use a reviewed trello-hub commit that contains `.github/workflows/trello-sync.yml`.
Copy `examples/consumer-workflow.yml` into the consumer repository as
`.github/workflows/trello.yml`. Replace **both** `REPLACE_WITH_FULL_SHA` values
with the same full commit SHA. There is no `v1` tag yet.

Do not use `pull_request_target`. The workflow skips fork PRs; no consumer code
is checked out. Keep the required `contents: read` and `pull-requests: read`
permissions. For CI failure handling, change the `workflow_run.workflows` name
to the consumer's actual CI workflow name; never select the Trello workflow
itself. Remove that trigger if CI failure handling is not wanted.

## 2. Prepare board configuration privately

Copy `workflow.example.yaml` to an ignored local `workflow.yaml`. Supply the
board shortlink, project prefix, exact list names and Experiment label. Set the
month format only after checking the current Done list:

| Existing list suffix | `done_month_format` |
| --- | --- |
| `2026-10` | `'%Y-%m'` |
| `October` | `'%B'` |
| `October 2026` | `'%B %Y'` |

The package does not guess this or create a missing monthly list. Set
`timezone: America/Vancouver` (or the board's actual timezone). When archiving
last month's Done list, ensure this month's open list exists before completion
events run.

In the consumer's GitHub **Settings → Secrets and variables → Actions →
Variables**, create `SPWF_CONFIG` containing this YAML. It contains board
configuration only, never tokens. This keeps private board details out of public
source. Repository variables are visible to people with repository access.

## 3. Run the local offline demo and read-only smoke

The offline demo in the README requires no accounts. For real validation, make
`TRELLO_KEY` and `TRELLO_TOKEN` available to the process through your local secret
manager or environment. The CLI does not automatically load `.env` files.

```sh
spwf smoke --config workflow.yaml --card YOUR_CARD_SHORTLINK
```

The smoke command uses GET requests only: board, configured lists and optionally
the selected card. Expected output is `read-only-smoke-passed` with zero writes.
If exact list names or the month format are wrong, correct the configuration and
rerun. Retain only sanitized response fixtures if adding recorded-response tests.

## 4. Configure credentials in GitHub

Create `TRELLO_KEY` and `TRELLO_TOKEN` as Actions secrets in the **consumer** repo,
not just trello-hub. Repository-scoped secrets are a straightforward first-consumer
choice; organization secrets can be adopted later with repository restrictions.
The template passes only the two named Trello secrets.

The runner uses GitHub's automatic `GITHUB_TOKEN` for current PR lookups. No
personal GitHub token is required for the reusable workflow. For local live
runs, provide a token with read access to the consumer's contents and PRs.

## 5. Preview the consumer, then enable one live card

Keep `dry-run: true` in the caller first. Without a snapshot, the run logs the
requested state as **unverified**. To see the final guarded plan offline, set the
optional `SPWF_SNAPSHOT` repository variable to a private JSON snapshot with the
shape shown in `examples/snapshot.json`: `board`, `lists` and `cards`. Replace
synthetic IDs with real facts; include `labels`, `closed`, `due`, `dueComplete`,
`idBoard`, `idList`, `id` and `shortLink`. Offline previews do not validate current
GitHub PR state.

After the read-only smoke and preview review, change `dry-run` to `false` and
use a designated non-reference test card. Prefer a non-Experiment card with no
due date for the first move.

1. Push `ws/<shortlink>-smoke` with an explicit `Trello: <shortlink> doing` trailer.
2. Verify the card's Doing list and comment containing SHA and run URL.
3. Rerun that job. Verify no additional comment or due-date write.
4. Open a PR for the branch; verify Review and the PR URL in the comment.
5. Rerun the earlier push job while the PR is open; verify it does not regress
   the card to Doing. Merge only when you actually want to complete the test card.
6. On an Experiment test card, verify completion targets Review, never Done.
7. Test CI failure handling separately, confirming Review cards stay in Review.

Read logs for `status: error` even when the consumer check is green. A failed
comment after a move requires inspection; do not assume a rerun will repair it.
No rollback or automatic write retry is implemented.

## Remaining activation work

- Confirm real list names, the monthly Done convention and Trello responses.
- Add configuration/secrets to the actual consumer and commit its caller.
- Validate same-repository and fork PR behavior in GitHub; forks must be skipped.
- Enable the desired Trello GitHub Power-Up manually if wanted.
- Record the first real move, then accumulate at least 10 successful pushes over
  two weeks before beginning the next integration milestone.

## API references

- [Trello boards](https://developer.atlassian.com/cloud/trello/rest/api-group-boards/)
- [Trello cards](https://developer.atlassian.com/cloud/trello/rest/api-group-cards/)
- [GitHub PRs associated with a commit](https://docs.github.com/en/rest/commits/commits#list-pull-requests-associated-with-a-commit)
- [GitHub concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
