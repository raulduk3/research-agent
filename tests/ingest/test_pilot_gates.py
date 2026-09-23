"""`ParallelGate` and `sampled_for_equivalence` (#207): the bucket PDF gate
runs its requests off the calling thread bounded by a fixed limit, since the
bucket states no rate rule, and the equivalence sample is a hash-fixed
one-in-fifty draw rather than a random one, so a rerun samples the same
families.
"""

from __future__ import annotations

import threading
import time

import pytest

from research_agent.ingest.pilot import ParallelGate, sampled_for_equivalence


def test_parallel_gate_bounds_concurrent_requests_and_returns_each_result() -> None:
    gate = ParallelGate(2)
    lock = threading.Lock()
    concurrent = 0
    peak = 0

    def work(n: int) -> int:
        nonlocal concurrent, peak
        with lock:
            concurrent += 1
            peak = max(peak, concurrent)
        time.sleep(0.05)
        with lock:
            concurrent -= 1
        return n

    futures = [gate.submit(lambda n=n: work(n)) for n in range(6)]
    assert sorted(future.result() for future in futures) == list(range(6))
    assert peak <= 2


def test_parallel_gate_limit_must_be_positive() -> None:
    with pytest.raises(ValueError):
        ParallelGate(0)


def test_sampled_for_equivalence_is_a_deterministic_hash_fixed_draw() -> None:
    assert sampled_for_equivalence("2305.00032") is True
    assert sampled_for_equivalence("2305.01937") is False
    # Fixed by the family id alone: a rerun samples exactly the same families.
    assert sampled_for_equivalence("2305.00032") is sampled_for_equivalence(
        "2305.00032"
    )
