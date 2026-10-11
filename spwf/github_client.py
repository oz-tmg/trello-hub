"""Read current PR state to make replayed events converge on the PR lifecycle."""

import re
from urllib.parse import quote

import requests

from spwf.github import Request, parse_event


class GitHubError(RuntimeError):
    """Safe-to-log GitHub error."""


class GitHubClient:
    def __init__(self, repository: str, token: str, *, session=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise GitHubError("Invalid GitHub repository")
        if not token:
            raise GitHubError("GITHUB_TOKEN is required for live PR precedence checks")
        self.repository = repository
        self._token = token
        self._session = session or requests.Session()

    def _get(self, path, **params):
        try:
            response = self._session.get(
                f"https://api.github.com/repos/{self.repository}/{path}",
                headers={"Authorization": f"Bearer {self._token}",
                         "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28"},
                params=params, timeout=(5, 20), allow_redirects=False,
            )
            if response.status_code != 200:
                raise GitHubError(f"GitHub lookup failed (HTTP {response.status_code})")
            return response.json()
        except (requests.RequestException, ValueError):
            raise GitHubError("GitHub lookup failed: transport or invalid JSON") from None

    def pull(self, number):
        if type(number) is not int or number <= 0:
            raise GitHubError("Invalid PR number")
        data = self._get(f"pulls/{number}")
        if not isinstance(data, dict):
            raise GitHubError("Invalid PR response")
        return data

    def associated(self, sha):
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise GitHubError("Invalid commit SHA")
        result = []
        # Do not trust arbitrary Link URLs with the authorization header.
        for page in range(1, 11):
            batch = self._get(f"commits/{sha}/pulls", per_page=100, page=page)
            if not isinstance(batch, list):
                raise GitHubError("Invalid associated PR response")
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise GitHubError("Associated PR pagination limit reached")

    def _pr_requests(self, pr, config):
        if pr["base"]["repo"]["full_name"] != self.repository:
            raise GitHubError("PR belongs to another repository")
        if (pr["head"].get("repo") or {}).get("full_name") != self.repository:
            return []  # Fork/deleted-head PRs must not influence privileged moves.
        # Fetching current PR state corrects a delayed opened event after merge.
        action = "opened" if pr["state"] == "open" else "closed"
        return parse_event("pull_request", {"action": action, "pull_request": pr}, config)

    def resolve(self, event, payload, config) -> list[Request]:
        try:
            if payload["repository"]["full_name"] != self.repository:
                raise GitHubError("Event belongs to another repository")
            if event == "pull_request":
                if payload.get("action") not in {"opened", "closed"}:
                    return []
                return self._pr_requests(self.pull(payload["number"]), config)
            parsed = parse_event(event, payload, config)
            resolved = []
            cache = {}
            for request in parsed:
                if request.ci_failed:
                    # Ignore old CI results after the branch has advanced.
                    head = self._get(f"commits/{quote(request.branch, safe='')}")
                    if head["sha"] != request.sha:
                        continue
                if event != "push":
                    resolved.append(request)
                    continue
                if request.sha not in cache:
                    prs = self.associated(request.sha)
                    cache[request.sha] = [self.pull(pr["number"]) for pr in prs]
                overrides = []
                closed_binding = False
                for pr in cache[request.sha]:
                    if (pr["head"].get("repo") or {}).get("full_name") != self.repository:
                        continue
                    current = self._pr_requests(pr, config)
                    overrides.extend(r for r in current if r.card == request.card)
                    if not current and pr["state"] == "closed":
                        # A closed/unmerged (or non-main) PR still supersedes a delayed
                        # branch creation event; closing a PR does not request a move.
                        bindings = parse_event("pull_request", {"action": "opened", "pull_request": pr}, config)
                        closed_binding |= any(r.card == request.card for r in bindings)
                # Multiple active PRs with different states are ambiguous; don't guess.
                if len({r.target for r in overrides}) > 1:
                    raise GitHubError("Conflicting PR states for the same card and commit")
                if overrides or not closed_binding:
                    resolved.append(overrides[-1] if overrides else request)
            # One final operation per card, preserving the last applicable command.
            return list({request.card: request for request in resolved}.values())
        except (KeyError, TypeError, AttributeError, ValueError):
            raise GitHubError("Invalid GitHub event or PR response") from None
