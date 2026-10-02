"""Operator commands for the swarm beta: ``python -m research_agent.beta``.

``serve`` runs the API. The others act on the same database without the API:
``migrate`` prepares the store, ``ingest`` runs one ingestion pass,
``advance`` lets idle agents take their next papers, ``budget`` prints the
budget state, and ``spec`` exports the editable swarm spec or applies one
from a file as a new revision.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from research_agent.beta import spec as specs
from research_agent.beta.config import ConfigError, load_config
from research_agent.beta.db import connect, utc_now
from research_agent.beta.errors import Refusal
from research_agent.beta.ingest import arxiv_fetcher
from research_agent.beta.models import ChatCompletionsClient
from research_agent.beta.service import Swarm


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="research_agent.beta", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    commands.add_parser("migrate", help="create or update the database")
    ingest = commands.add_parser("ingest", help="run one arXiv ingestion pass")
    ingest.add_argument("--category", action="append")
    ingest.add_argument("--limit", type=int)
    ingest.add_argument("--no-advance", action="store_true")
    commands.add_parser("advance", help="let idle agents take their next papers")
    commands.add_parser("budget", help="print the budget state")
    spec = commands.add_parser("spec", help="export or apply the swarm spec")
    spec.add_argument("action", choices=("export", "apply"))
    spec.add_argument("file", nargs="?", type=Path)
    spec.add_argument("--note", default="")
    spec.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        config = load_config()
    except ConfigError as error:
        print(f"configuration refused: {error}", file=sys.stderr)
        return 2

    if args.command == "serve":
        import uvicorn

        from research_agent.beta.app import create_app

        uvicorn.run(create_app(config), host=args.host, port=args.port)
        return 0

    client = ChatCompletionsClient(config.provider) if config.provider else None
    swarm = Swarm(config, client, utc_now, arxiv_fetcher(config.arxiv_api))
    swarm.prepare()
    try:
        if args.command == "migrate":
            result: object = {"database": str(config.database), "status": "ready"}
        elif args.command == "ingest":
            result = swarm.ingest(
                args.category, args.limit, False if args.no_advance else None
            )
            swarm.execute([item["run_id"] for item in result["advance"]["started"]])
        elif args.command == "advance":
            result = swarm.advance()
            swarm.execute([item["run_id"] for item in result["started"]])
        elif args.command == "budget":
            result = swarm.state()[2].full()
        elif args.action == "export":
            revision, document = swarm.state()[:2]
            result = {"revision": revision, "spec": document}
        else:
            if args.file is None:
                parser.error("spec apply needs a file")
            proposed = json.loads(args.file.read_text(encoding="utf-8"))
            with connect(config.database) as db:
                result = specs.apply_spec(
                    db,
                    proposed.get("spec", proposed),
                    actor="operator",
                    now=utc_now(),
                    note=args.note,
                    dry_run=args.dry_run,
                )
    except Refusal as refusal:
        print(f"refused: {refusal.message}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
