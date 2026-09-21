"""Local storage administration; no worker or paid provider is started."""

import argparse
import os
import sys

import psycopg

from research_agent.platform.version import VersionUnavailableError, get_version
from research_agent.storage.database import Database
from research_agent.storage.migrate import migrate, require_schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="store_true")
    parser.add_argument("command", choices=("migrate", "check-schema"), nargs="?")
    args = parser.parse_args()
    if args.version:
        try:
            print(get_version())
        except VersionUnavailableError:
            print(
                "Product version requires a Git checkout with a version tag.",
                file=sys.stderr,
            )
            return 1
        return 0
    if args.command is None:
        parser.error("a command is required")
    dsn = os.environ.get("RESEARCH_AGENT_STORAGE_DSN")
    if not dsn:
        parser.error("RESEARCH_AGENT_STORAGE_DSN is required")
    database = Database(dsn)
    try:
        if args.command == "migrate":
            migrate(database)
        require_schema(database)
    except (psycopg.Error, RuntimeError):
        print(
            "Storage schema check failed; inspect database configuration.",
            file=sys.stderr,
        )
        return 1
    print("Storage schema is current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
