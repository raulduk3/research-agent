"""Shared pieces for the swarm beta tests: a clock, a scripted model, feeds."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from research_agent.beta.config import BetaConfig, ModelProvider
from research_agent.beta.models import (
    Message,
    ModelCallFailed,
    ModelResponse,
    ToolCall,
    ToolSchema,
)
from research_agent.beta.papers import PaperEntry

#: A quarter of a dollar in and 1.25 out per million tokens, near the real
#: provider's prices; the default reply (1,000 in, 200 out) costs 500.
PROVIDER = ModelProvider(
    name="test-provider",
    endpoint="https://models.invalid/v1/chat/completions",
    api_key="test-key",
    model="test-model",
    input_usd_per_mtok=Decimal("0.25"),
    output_usd_per_mtok=Decimal("1.25"),
)

ABSTRACT = (
    "We study tool-using agents whose traces are visible to reviewers. "
    "Visible traces change the training signal and reduce unsupported claims."
)


class FakeClock:
    """A clock the test moves by hand."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def call(name: str, arguments: dict[str, Any] | str, call_id: str = "") -> ToolCall:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    parsed = arguments if isinstance(arguments, dict) else None
    return ToolCall(call_id or f"call-{name}", name, parsed, raw)


def reply(
    *calls: ToolCall,
    text: str = "",
    input_tokens: int = 1000,
    output_tokens: int = 200,
    reported: bool = True,
) -> ModelResponse:
    return ModelResponse(
        text=text,
        tool_calls=tuple(calls),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usage_reported=reported,
        model="test-model",
        finish_reason="tool_calls" if calls else "stop",
    )


class ScriptedClient:
    """A model that answers from a script and records what it was asked."""

    def __init__(self, script: Sequence[ModelResponse | Exception]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        *,
        max_output_tokens: int,
        temperature: float,
    ) -> ModelResponse:
        self.requests.append(
            {
                "messages": [dict(message) for message in messages],
                "tools": [tool["function"]["name"] for tool in tools],
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
            }
        )
        if not self.script:
            raise ModelCallFailed("the script has no further answer")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def reading(quote: str = "Visible traces change the training signal") -> dict[str, Any]:
    """A complete reading whose one claim quotes the stored abstract."""
    return {
        "summary": "Trace visibility changes what agents learn.",
        "claims": [
            {"text": "Visible traces alter the signal.", "evidence": [{"quote": quote}]}
        ],
        "objections": ["No comparison against hidden traces at equal cost."],
        "related_papers": [],
        "idea_seeds": ["Measure claim support with and without trace review."],
    }


def entry(
    paper_id: str = "2609.00001",
    *,
    version: int = 1,
    title: str = "Tool-using agents learn when traces are visible",
    abstract: str = ABSTRACT,
    primary: str = "cs.AI",
    categories: tuple[str, ...] = ("cs.AI",),
    published: str = "2026-09-10T08:00:00Z",
) -> PaperEntry:
    return PaperEntry(
        id=paper_id,
        version=version,
        title=title,
        abstract=abstract,
        authors=("Ada Reader", "Sam Tracer"),
        primary_category=primary,
        categories=categories,
        published_at=published,
        updated_at=published,
        abs_url=f"https://arxiv.org/abs/{paper_id}v{version}",
        pdf_url=f"https://arxiv.org/pdf/{paper_id}v{version}",
    )


def feed(*entries: PaperEntry, extra: str = "") -> str:
    """An arXiv Atom feed carrying the given entries."""
    blocks = []
    for item in entries:
        categories = "".join(
            f'<category term="{term}" scheme="http://arxiv.org/schemas/atom"/>'
            for term in item.categories
        )
        authors = "".join(
            f"<author><name>{name}</name></author>" for name in item.authors
        )
        blocks.append(
            f"<entry><id>http://arxiv.org/abs/{item.id}v{item.version}</id>"
            f"<title>{item.title}</title><updated>{item.updated_at}</updated>"
            f'<link href="{item.abs_url}" rel="alternate" type="text/html"/>'
            f'<link href="{item.pdf_url}" rel="related" type="application/pdf"'
            f' title="pdf"/><summary>  {item.abstract}\n</summary>{categories}'
            f"<published>{item.published_at}</published>"
            f'<arxiv:primary_category term="{item.primary_category}"/>'
            f"{authors}</entry>"
        )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        '<feed xmlns:arxiv="http://arxiv.org/schemas/atom"'
        ' xmlns="http://www.w3.org/2005/Atom">'
        "<title>arXiv Query</title>" + "".join(blocks) + extra + "</feed>"
    )


def config(tmp_path: Path, **overrides: Any) -> BetaConfig:
    values: dict[str, Any] = {
        "database": tmp_path / "swarm.sqlite3",
        "session_secret": "test-session-secret",
        "island_passwords": {"cs": "cs-pass", "quant": "quant-pass"},
        "operator_token": "operator-pass",
        "allowed_origins": ("https://swarm.example.app",),
        "provider": PROVIDER,
        "arxiv_delay_seconds": 0.0,
    }
    values.update(overrides)
    return BetaConfig(**values)
