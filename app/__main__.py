from __future__ import annotations

import argparse

from app.config import load_config
from app.logging_config import configure_logging
from app.migrations import apply_migrations


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate", help="Apply unapplied database migrations")

    args = parser.parse_args()
    configure_logging()

    if args.command == "migrate":
        load_config()
        apply_migrations()


if __name__ == "__main__":
    main()
