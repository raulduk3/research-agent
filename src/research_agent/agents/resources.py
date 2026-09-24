"""Sample what one run cost the machine and build its resources record (#330).

The runner executes a run in its own process, so its CPU and memory are
``resource.getrusage`` of the process and its children: user and system
CPU time summed, peak resident memory the larger of the two. Host load is
read at the start and the end. The model calls come from the agent model
client's own usage records (#307), each with the identity the provider
returned, its latency and its bytes each way. No launcher reports a worker
image digest or a run log yet, so both stay ``None`` until one does.
Nothing here reaches the agent.
"""

from __future__ import annotations

import os
import resource
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from research_agent.agents.model_client import TurnUsage

__all__ = ["RunClock", "resources_record"]

#: ``ru_maxrss`` is bytes on macOS and kibibytes elsewhere.
_MAXRSS_UNIT = 1 if sys.platform == "darwin" else 1024


def _instant(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def _load() -> list[int]:
    """Host load over 1, 5 and 15 minutes, in hundredths."""

    return [round(value * 100) for value in os.getloadavg()]


@dataclass(frozen=True, slots=True)
class RunClock:
    """The run's start: wall clock and host load, taken before any model call."""

    started_at: float = field(default_factory=time.time)
    load_start: list[int] = field(default_factory=_load)


def resources_record(
    clock: RunClock,
    usage: Sequence[TurnUsage],
    *,
    model_endpoint: str,
    tool_service: str,
    now: Callable[[], float] = time.time,
    load: Callable[[], list[int]] = _load,
    rusage: Callable[[int], Any] = resource.getrusage,
) -> dict[str, Any]:
    """The run's resources as ``POST /v1/runs/{id}/resources`` takes them,
    without the ``run_id`` the route carries."""

    ended_at = now()
    own = rusage(resource.RUSAGE_SELF)
    children = rusage(resource.RUSAGE_CHILDREN)
    return {
        "started_at": _instant(clock.started_at),
        "first_model_call_at": _instant(usage[0].started_at) if usage else None,
        "last_model_call_at": _instant(
            usage[-1].started_at + usage[-1].latency_ms / 1000
        )
        if usage
        else None,
        "ended_at": _instant(ended_at),
        "model_endpoint": model_endpoint,
        "tool_service": tool_service,
        "model_calls": [
            {
                "turn_index": call.turn_index,
                "model": call.reported_model_id,
                "revision": call.reported_revision,
                "input_tokens": call.input_tokens,
                "cached_input_tokens": call.cached_input_tokens,
                "output_tokens": call.output_tokens,
                "latency_ms": call.latency_ms,
                "bytes_sent": call.bytes_sent,
                "bytes_received": call.bytes_received,
            }
            for call in usage
        ],
        "process": {
            "kind": "in_process",
            "cpu_user_ms": round((own.ru_utime + children.ru_utime) * 1000),
            "cpu_system_ms": round((own.ru_stime + children.ru_stime) * 1000),
            "peak_rss_bytes": max(own.ru_maxrss, children.ru_maxrss) * _MAXRSS_UNIT,
            "load_start": clock.load_start,
            "load_end": load(),
        },
        "image_digest": None,
        "run_log": None,
    }
