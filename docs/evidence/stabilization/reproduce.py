"""Reproduce four baseline audit findings without network calls."""

from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from research_agent.beta.budget import budget_state
from research_agent.beta.chat import answer_question
from research_agent.beta.db import connect, migrate
from research_agent.beta.ingest import run_ingestion_pass
from research_agent.beta.models import ChatCompletionsClient
from research_agent.beta.service import Swarm
from research_agent.beta.spec import current_spec, ensure_seed
from tests.beta.helpers import (
    PROVIDER,
    FakeClock,
    ScriptedClient,
    config,
    entry,
    feed,
    reply,
)
from tests.beta.test_runs import _create, _store


def main():
    with TemporaryDirectory() as temporary:
        cfg = config(Path(temporary))
        clock = FakeClock()
        migrate(cfg.database)
        with connect(cfg.database) as db:
            ensure_seed(db, clock())
            db.commit()
            _store(db, clock)
            run_id = _create(db, clock)
            assert (
                db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[
                    0
                ]
                == "queued"
            )
        Swarm(cfg, None, clock, lambda *_: "").prepare()
        with connect(cfg.database) as db:
            row = db.execute(
                "SELECT status,failure FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            assert tuple(row) == ("failed", "interrupted_by_restart")
            print("CONFIRMED: second preparation fails another owner's queued run")
            _, spec = current_spec(db)
            state = budget_state(db, spec, clock(), True)

            def fetch(category, limit):
                return feed(*[entry(f"2609.{i:05d}") for i in range(1, 26)][:limit])

            summaries = []
            for _ in range(8):
                summaries.append(
                    run_ingestion_pass(
                        db,
                        spec,
                        state.plan,
                        fetch=fetch,
                        clock=clock,
                        categories=["cs.AI"],
                        limit=20,
                        sleep=lambda _: None,
                    )
                )
            assert db.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 20
            assert [s["stored"] for s in summaries][-3:] == [0, 0, 0]
            print("CONFIRMED: ingestion stalls at 20 of 25 source records")
            answer = answer_question(
                db,
                island=next(i for i in spec["islands"] if i["id"] == "cs"),
                message="visible traces",
                synthesize=True,
                state=state,
                provider=cfg.provider,
                client=ScriptedClient(
                    [
                        reply(
                            text="Unlinked unsupported statement about an invented experiment."
                        )
                    ]
                ),
                clock=clock,
            )
            assert answer["supported"] is True
            assert (
                answer["answer"]
                == "Unlinked unsupported statement about an invented experiment."
            )
            print("CONFIRMED: invented unlinked chat prose is marked supported")
    cases = [
        ({"choices": [{"message": "bad"}]}, AttributeError),
        (
            {
                "choices": [{"message": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": "bad", "completion_tokens": 1},
            },
            ValueError,
        ),
    ]
    for body, expected in cases:
        client = ChatCompletionsClient(
            PROVIDER,
            httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
        )
        try:
            client.complete(
                [{"role": "user", "content": "x"}],
                [],
                max_output_tokens=1,
                temperature=0,
            )
        except expected:
            print(
                f"CONFIRMED: malformed provider response escapes as {expected.__name__}"
            )
        else:
            raise AssertionError(f"Expected {expected.__name__}")


if __name__ == "__main__":
    main()
