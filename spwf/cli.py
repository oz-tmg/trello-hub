"""Scaffold entrypoint; live synchronization is not implemented yet."""

import argparse
from importlib.metadata import version


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="spwf",
        description="Trello workflow automation (local scaffold; no live commands yet).",
    )
    parser.add_argument("--version", action="version", version=version("spwf"))
    parser.parse_args()
    parser.print_help()
    return 0
