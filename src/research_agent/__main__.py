"""Operator entry point: storage administration and one start command per role.

No paid provider is called here; each role launcher refuses to start without
its declared secrets or with a launch profile other than the declared one.
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg

from research_agent.platform.version import VersionUnavailableError, get_version
from research_agent.platform.anchoring import AnchorBindRefused
from research_agent.platform.collection import check_collection_readiness
from research_agent.platform.services.config import LaunchRefused
from research_agent.platform.startup import ROLE_COMMANDS, launch_role
from research_agent.platform.storage_service import (
    bind_storage_anchor,
    serve_storage,
)
from research_agent.storage.database import Database
from research_agent.storage.migrate import migrate, require_schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="store_true")
    parser.add_argument(
        "command",
        choices=(
            "migrate",
            "check-schema",
            "collection-readiness",
            "serve-storage",
            "bind-anchor",
            *ROLE_COMMANDS,
        ),
        nargs="?",
    )
    parser.add_argument("--config", type=Path, help="the role's launch configuration")
    parser.add_argument(
        "--once", action="store_true", help="serve-ingest: run one day pass and exit"
    )
    parser.add_argument("--compose-file", type=Path, default=Path("compose.yaml"))
    parser.add_argument("--storage-config", type=Path)
    parser.add_argument("--isolation-evidence", type=Path)
    parser.add_argument("--receiver", help="bind-anchor: the receiver's https URL")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="bind-anchor: record only after one acknowledged round trip",
    )
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
    if args.command in ROLE_COMMANDS:
        if args.config is None:
            parser.error("--config is required")
        try:
            launch_role(args.command, args.config, once=args.once)
        except LaunchRefused as error:
            print(f"Launch refused: {error}", file=sys.stderr)
            return 1
        except (ValueError, OSError, psycopg.Error) as error:
            # The error text may carry a connection string; name its kind only.
            print(
                f"Launch failed: {type(error).__name__}; inspect the role's configuration.",
                file=sys.stderr,
            )
            return 1
        return 0
    if args.command == "serve-storage":
        if args.storage_config is None:
            parser.error("--storage-config is required")
        try:
            serve_storage(args.storage_config)
        except ValueError as error:
            print(f"Storage service configuration failed: {error}", file=sys.stderr)
            return 1
        return 0
    if args.command == "bind-anchor":
        if args.storage_config is None or args.receiver is None:
            parser.error("--storage-config and --receiver are required")
        if not args.verify:
            parser.error("bind-anchor records only a verified binding; pass --verify")
        try:
            binding = bind_storage_anchor(args.storage_config, args.receiver)
        except AnchorBindRefused as error:
            print(f"Anchor binding refused: {error}", file=sys.stderr)
            return 1
        except (ValueError, OSError, RuntimeError, psycopg.Error) as error:
            # The error text may carry a connection string; name its kind only.
            print(
                f"Anchor binding failed: {type(error).__name__}; "
                "inspect the storage configuration.",
                file=sys.stderr,
            )
            return 1
        print(
            "Anchor receiver bound; acknowledged sequence "
            f"{binding.last_acknowledged_sequence}."
        )
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
