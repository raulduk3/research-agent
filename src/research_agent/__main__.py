"""Local storage administration; no worker or paid provider is started."""

import argparse
import os
import sys
from pathlib import Path

import psycopg

from research_agent.platform.version import VersionUnavailableError, get_version
from research_agent.platform.collection import check_collection_readiness
from research_agent.platform.storage_service import serve_storage
from research_agent.storage.database import Database
from research_agent.storage.migrate import migrate, require_schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="store_true")
    parser.add_argument(
        "command",
        choices=("migrate", "check-schema", "collection-readiness", "serve-storage"),
        nargs="?",
    )
    parser.add_argument("--compose-file", type=Path, default=Path("compose.yaml"))
    parser.add_argument("--storage-config", type=Path)
    parser.add_argument("--isolation-evidence", type=Path)
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
    if args.command == "collection-readiness":
        if args.storage_config is None:
            parser.error("--storage-config is required")
        result = check_collection_readiness(
            compose_file=args.compose_file,
            storage_config=args.storage_config,
            isolation_evidence=args.isolation_evidence,
        )
        if result.ready:
            print("Collection readiness is evidenced; start remains operator-owned.")
            return 0
        print(
            "Collection readiness refused: " + ", ".join(result.missing),
            file=sys.stderr,
        )
        return 1
    if args.command == "serve-storage":
        if args.storage_config is None:
            parser.error("--storage-config is required")
        try:
            serve_storage(args.storage_config)
        except ValueError as error:
            print(f"Storage service configuration failed: {error}", file=sys.stderr)
            return 1
        return 0
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
