"""Compatibility entrypoint used by workflow consumers."""
import sys
from spwf.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["sync", *sys.argv[1:]]))
