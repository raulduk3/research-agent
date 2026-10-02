"""The beta image installs what the lockfile pins and ships the beta alone."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy" / "beta"


def _pins() -> dict[str, str]:
    text = (DEPLOY / "requirements.txt").read_text(encoding="utf-8")
    return dict(re.findall(r"^([a-z0-9._-]+)==(\S+)", text, flags=re.MULTILINE))


def test_the_beta_requirements_are_the_lockfile_versions() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked: dict[str, set[str]] = {}
    for package in lock["package"]:
        # The project's own entry has no version; it is not a dependency.
        if "version" in package:
            locked.setdefault(package["name"], set()).add(package["version"])

    pins = _pins()

    assert {"fastapi", "uvicorn", "httpx", "pydantic", "starlette"} <= set(pins)
    for name, version in pins.items():
        assert version in locked.get(name, set()), f"{name}=={version} is not locked"
    # The beta needs no numerical or model stack; none may ride along.
    assert not {"torch", "transformers", "numpy", "scipy", "psycopg"} & set(pins)


def test_the_image_copies_the_beta_package_and_nothing_else_of_the_source() -> None:
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    copies = [
        line.split()[1] for line in dockerfile.splitlines() if line.startswith("COPY ")
    ]

    assert copies == [
        "deploy/beta/requirements.txt",
        "src/research_agent/__init__.py",
        "src/research_agent/beta",
    ]
    assert "--require-hashes" in dockerfile


def test_the_beta_imports_nothing_from_the_earlier_platform() -> None:
    package = ROOT / "src" / "research_agent" / "beta"
    for source in sorted(package.glob("*.py")):
        for line in source.read_text(encoding="utf-8").splitlines():
            if line.startswith(("from research_agent", "import research_agent")):
                assert "research_agent.beta" in line, f"{source.name}: {line}"


def test_the_example_environment_names_every_variable_the_config_reads() -> None:
    config = (ROOT / "src/research_agent/beta/config.py").read_text(encoding="utf-8")
    read = set(re.findall(r'"(RESEARCH_AGENT_[A-Z_]+)"', config))
    example = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    named = set(
        re.findall(r"^#? ?(RESEARCH_AGENT_[A-Z_]+)=", example, flags=re.MULTILINE)
    )

    assert read == named
