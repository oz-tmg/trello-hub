"""Offline previews by default; explicit live synchronization and read-only smoke."""

import argparse
from dataclasses import asdict
from importlib.metadata import version
import json
import os
from pathlib import Path

from pydantic import ValidationError

from spwf.config import ConfigError, load_config
from spwf.github import EventError, parse_event
from spwf.github_client import GitHubClient, GitHubError
from spwf.sync import list_id, plan, synchronize
from spwf.state import State
from spwf.trello import Board, Card, List, TrelloClient, TrelloError


def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise ConfigError("Cannot read JSON input") from None


def emit(value):
    text = json.dumps(value, ensure_ascii=True)
    for name in ("TRELLO_KEY", "TRELLO_TOKEN", "GITHUB_TOKEN"):
        secret = os.environ.get(name)
        if secret:
            text = text.replace(json.dumps(secret)[1:-1], "[redacted]")
    print(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="spwf", description=__doc__)
    parser.add_argument("--version", action="version", version=version("spwf"))
    commands = parser.add_subparsers(dest="command")
    sync = commands.add_parser("sync", help="Preview an event offline, or apply it with --live")
    sync.add_argument("--config", default="workflow.yaml")
    sync.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME"), required=False)
    sync.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH"), required=False)
    sync.add_argument("--snapshot", help="Offline JSON board/lists/cards snapshot; never used in live mode")
    mode = sync.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--dry-run", action="store_true", help="Default; no network calls")
    sync.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    sync.add_argument("--run-url", default="")
    sync.add_argument("--soft-fail", action="store_true", help="Log sanitized integration failures and exit 0")
    smoke = commands.add_parser("smoke", help="Read-only board/list/card validation")
    smoke.add_argument("--config", default="workflow.yaml")
    smoke.add_argument("--card", help="Optional card shortlink to verify ownership")
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        config = load_config(args.config)
        if args.command == "sync":
            if not args.event_name or not args.event_path:
                raise ConfigError("Event name and event path are required")
            if args.live and args.snapshot:
                raise ConfigError("Fixture snapshots cannot be used in live mode")
            payload = _json(args.event_path)
            if not isinstance(payload, dict):
                raise ConfigError("Event must be a JSON object")
            if not args.live:
                requests = parse_event(args.event_name, payload, config)
                if not args.snapshot:
                    for request in requests:
                        emit({"status": "unverified", "card": request.card,
                              "requested_state": request.target.value,
                              "note": "No card facts or current PR lookup; no final move planned"})
                else:
                    snapshot = _json(args.snapshot)
                    board = Board.model_validate(snapshot["board"])
                    if config.board not in (board.id, snapshot["board"].get("shortLink")):
                        raise ConfigError("Snapshot belongs to another board")
                    lists = [List.model_validate(item) for item in snapshot["lists"]]
                    cards = [Card.model_validate(item) for item in snapshot["cards"]]
                    for request in requests:
                        matches = [card for card in cards if card.shortLink == request.card]
                        if len(matches) != 1:
                            raise ConfigError("Snapshot card missing or ambiguous")
                        result = plan(request, matches[0], board, lists, config, run_url=args.run_url)
                        emit({**asdict(result), "status": "dry-run", "pr_precedence": "not queried offline"})
                emit({"status": "preview-complete", "requests": len(requests), "network_calls": 0})
                return 0
            github = GitHubClient(args.repository or "", os.environ.get("GITHUB_TOKEN", ""))
            requests = github.resolve(args.event_name, payload, config)
            if not requests:
                emit({"status": "noop", "requests": 0})
                return 0
        client = TrelloClient(config.board, os.environ.get("TRELLO_KEY", ""), os.environ.get("TRELLO_TOKEN", ""))
        if args.command == "smoke":
            client.board()
            lists = client.lists()
            for name in (config.lists.doing, config.lists.blocked, config.lists.review, config.lists.reference,
                         config.target_list(State.DONE, month_label=config.current_month())):
                list_id(lists, name)
            if args.card:
                client.get_card(args.card)
            emit({"status": "read-only-smoke-passed", "writes": 0})
        else:
            for result in synchronize(requests, client, config, run_url=args.run_url):
                emit(result)
        return 0
    except (ConfigError, EventError, GitHubError, TrelloError) as exc:
        emit({"status": "error", "message": str(exc)})
    except (ValidationError, KeyError, TypeError, AttributeError, ValueError):
        emit({"status": "error", "message": "Invalid input data"})
    except Exception:
        # The reusable workflow must not fail the consumer or leak exception data.
        emit({"status": "error", "message": "Unexpected synchronization failure"})
    return 0 if getattr(args, "soft_fail", False) else 1
