"""The operator command that provisions a rater principal (PL-22, #369)."""

from __future__ import annotations

import io
import stat
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from research_agent.platform.raters import main
from research_agent.storage.raters import validate_rater_payload
from research_agent.web.auth import RaterPrincipal


class Storage:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def provision_rater(self, **call: Any) -> None:
        validate_rater_payload(
            "provision",
            {
                "rater_id": str(call["rater_id"]),
                "island": call["island"],
                "salt": call["salt"],
                "credential_hash": call["credential_hash"],
            },
        )
        self.calls.append(call)


def run(storage: Storage, *argv: str) -> tuple[int, str]:
    out = io.StringIO()
    return main(list(argv), storage=storage, out=out), out.getvalue()


@pytest.mark.parametrize(
    ("island", "stored"),
    [("cs", "cs"), ("quant-ph", "quant_ph"), ("quant_ph", "quant_ph")],
)
def test_writes_an_owner_only_credential_and_sends_its_salted_hash(
    tmp_path: Path, island: str, stored: str
) -> None:
    storage = Storage()
    path = tmp_path / "rater.credential"
    status, printed = run(storage, "--island", island, "--credential-file", str(path))

    assert status == 0
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    credential = path.read_text().strip()
    assert credential not in printed
    [call] = storage.calls
    assert printed == f"rater {call['rater_id']} credential {path}\n"
    assert call["island"] == stored
    assert credential not in call.values()
    principal = RaterPrincipal(
        call["rater_id"], stored, call["salt"], call["credential_hash"]
    )
    assert principal.matches(credential)
    assert not principal.matches(credential + "x")


def test_a_rerun_with_the_rater_id_replays_without_overwriting(
    tmp_path: Path,
) -> None:
    storage = Storage()
    path = tmp_path / "rater.credential"
    run(storage, "--island", "cs", "--credential-file", str(path))
    written = path.read_text()
    rater_id = str(storage.calls[0]["rater_id"])

    status, _ = run(
        storage,
        "--island",
        "cs",
        "--credential-file",
        str(path),
        "--rater-id",
        rater_id,
    )

    assert status == 0
    assert path.read_text() == written
    first, second = storage.calls
    assert first == second


def test_an_existing_file_without_a_rater_id_is_refused(tmp_path: Path) -> None:
    storage = Storage()
    path = tmp_path / "rater.credential"
    path.write_text("kept\n")

    status, printed = run(storage, "--island", "cs", "--credential-file", str(path))

    assert (status, printed, storage.calls) == (2, "", [])
    assert path.read_text() == "kept\n"


@pytest.mark.parametrize("island", ["q-bio", "physics", "quant ph"])
def test_an_island_without_a_rater_principal_is_refused(
    tmp_path: Path, island: str, capsys: pytest.CaptureFixture[str]
) -> None:
    storage = Storage()
    path = tmp_path / "rater.credential"

    status, _ = run(storage, "--island", island, "--credential-file", str(path))

    assert (status, storage.calls, path.exists()) == (2, [], False)
    if island == "q-bio":
        assert "#371" in capsys.readouterr().err


def test_distinct_raters_get_distinct_credentials_and_salts(tmp_path: Path) -> None:
    storage = Storage()
    run(storage, "--island", "cs", "--credential-file", str(tmp_path / "a"))
    run(storage, "--island", "quant-ph", "--credential-file", str(tmp_path / "b"))

    first, second = storage.calls
    assert (tmp_path / "a").read_text() != (tmp_path / "b").read_text()
    assert first["salt"] != second["salt"]
    assert isinstance(first["rater_id"], UUID)
    assert first["idempotency_key"] != second["idempotency_key"]
