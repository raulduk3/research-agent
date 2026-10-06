"""Exercise the real beta API for the browser's executable contract tests."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from httpx import Response

from tests.beta.helpers import reply
from tests.beta.test_api import PAPER, Api, _read


def accepted(response: Response) -> Any:
    assert response.is_success, response.text
    return response.json()


def samples(directory: Path) -> dict[str, Any]:
    requests: dict[str, Any] = {
        "login": {"island": "cs", "password": "cs-pass"},
        "chat": {"message": "visible traces"},
        "settings": {"evolution_enabled": False},
        "genome": {
            "island_id": "cs",
            "parent_id": "cs-reader",
            "prompt": "Read for flaws.",
            "tools": "paper_text,submit_reading",
        },
        "selection": {},
        "deselection": {},
        "like": {"target_kind": "paper", "target_id": PAPER},
        "agentEdit": {"fields": {"active": False}},
    }
    api = Api(directory)
    with api.http:
        login = accepted(api.http.post("/api/v1/login", json=requests["login"]))
        cs = {"Authorization": f"Bearer {login['token']}"}
        operator = {"Authorization": "Bearer operator-pass"}
        run_id = _read(api, operator)
        answers = {
            "login": login,
            "storm": accepted(api.http.get("/api/v1/public/storm")),
            "brief": accepted(
                api.http.get(
                    "/api/v1/public/brief?include=grade,numbers,papers,agents&limit=100"
                )
            ),
            "activity": accepted(api.http.get("/api/v1/public/activity")),
            "publicPaper": accepted(api.http.get(f"/api/v1/public/papers/{PAPER}")),
            "island": accepted(api.http.get("/api/v1/islands/cs", headers=cs)),
            "paper": accepted(api.http.get(f"/api/v1/papers/{PAPER}", headers=cs)),
            "run": accepted(api.http.get(f"/api/v1/runs/{run_id}", headers=cs)),
        }
        api.model.script = [reply(text="Visible traces change what agents learn [1].")]
        answers["chat"] = accepted(
            api.http.post("/api/v1/chat", json=requests["chat"], headers=cs)
        )
        answers["settings"] = accepted(
            api.http.post(
                "/api/v1/islands/cs/settings",
                json=requests["settings"],
                headers=cs,
            )
        )
        answers["genome"] = accepted(
            api.http.post(
                "/api/v1/genomes",
                json=requests["genome"],
                headers=cs,
            )
        )
        answers["selection"] = accepted(
            api.http.post(
                f"/api/v1/papers/{PAPER}/select", json=requests["selection"], headers=cs
            )
        )
        answers["deselection"] = accepted(
            api.http.post(
                f"/api/v1/papers/{PAPER}/deselect",
                json=requests["deselection"],
                headers=cs,
            )
        )
        answers["like"] = accepted(
            api.http.post(
                "/api/v1/likes",
                json=requests["like"],
                headers=cs,
            )
        )
        answers["agentEdit"] = accepted(
            api.http.post(
                "/api/v1/agents/cs-reader",
                json=requests["agentEdit"],
                headers=cs,
            )
        )
        refused = api.http.get("/api/v1/islands/cs")
        assert refused.status_code == 401
        answers["error"] = refused.json()
        answers["requests"] = requests
        return answers


if __name__ == "__main__":
    with TemporaryDirectory() as temporary:
        print(json.dumps(samples(Path(temporary))))
