"""Host graphics-device selection: no CPU fallback (MD-06, Appendix A)."""

from __future__ import annotations

import pytest

from research_agent.contracts.primitives import ContractValidationError
from research_agent.models.backend import detect_host_device


def test_detect_host_device_prefers_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    assert detect_host_device() == "cuda"


def test_detect_host_device_falls_back_to_mps(monkeypatch: pytest.MonkeyPatch) -> None:
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    assert detect_host_device() == "mps"


def test_detect_host_device_refuses_a_host_with_no_graphics_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    with pytest.raises(ContractValidationError):
        detect_host_device()


# --- device pooling and sub-batching --------------------------------------------


def _random_encoding(
    seed: int, tokens: int, dimension: int = 8
) -> tuple[list[list[float]], list[int]]:
    import random

    rng = random.Random(seed)
    hidden = [[rng.uniform(-2.0, 2.0) for _ in range(dimension)] for _ in range(tokens)]
    real = rng.randint(1, tokens)
    mask = [1] * real + [0] * (tokens - real)
    return hidden, mask


def test_pool_hidden_states_matches_the_python_pooling_row_for_row() -> None:
    """The prohibited alternative is a device pooling that drifts from
    ``mean_pool_unit_l2``: both accumulate in float64 and cast to float32, so
    they agree to the last float32 bit or the next one."""
    import torch

    from research_agent.models.backend import pool_hidden_states
    from research_agent.models.embedding import TokenEncoding, mean_pool_unit_l2

    rows = [_random_encoding(seed, tokens=7) for seed in range(5)]
    hidden = torch.tensor([hidden for hidden, _ in rows], dtype=torch.float32)
    mask = torch.tensor([mask for _, mask in rows], dtype=torch.int64)
    pooled = pool_hidden_states(hidden, mask)
    assert len(pooled) == 5
    for (hidden_row, mask_row), vector in zip(rows, pooled, strict=True):
        # The Python path sees the float32 tensor's values, as the backend would give it.
        seen = torch.tensor(hidden_row, dtype=torch.float32).tolist()
        expected = mean_pool_unit_l2(
            TokenEncoding(tuple(map(tuple, seen)), tuple(mask_row), len(mask_row)), 8
        )
        assert max(abs(a - b) for a, b in zip(vector, expected, strict=True)) <= 1e-6
        assert abs(sum(v * v for v in vector) - 1.0) < 1e-5


def test_pool_hidden_states_refuses_a_fully_masked_row() -> None:
    import torch

    from research_agent.contracts.primitives import ContractValidationError
    from research_agent.models.backend import pool_hidden_states

    hidden = torch.ones((1, 3, 4))
    mask = torch.zeros((1, 3), dtype=torch.int64)
    with pytest.raises(ContractValidationError, match="unmasked"):
        pool_hidden_states(hidden, mask)


def test_sub_batches_group_by_ascending_length_and_cover_every_index() -> None:
    from research_agent.models.backend import sub_batches

    groups = sub_batches([50, 5, 500, 7, 60], 2)
    assert groups == [[1, 3], [0, 4], [2]]
    assert sorted(index for group in groups for index in group) == [0, 1, 2, 3, 4]
    assert sub_batches([], 3) == []


class _FakeTokenizer:
    """Token count is the text length; padded batches are (batch, longest)."""

    def __call__(self, texts: object, **kwargs: object) -> dict[str, object]:
        import torch

        if isinstance(texts, str):
            return {"input_ids": list(range(len(texts)))}
        assert isinstance(texts, list)
        longest = max(len(text) for text in texts)
        ids = torch.zeros((len(texts), longest), dtype=torch.int64)
        mask = torch.zeros((len(texts), longest), dtype=torch.int64)
        for row, text in enumerate(texts):
            for column, character in enumerate(text):
                ids[row, column] = ord(character)
                mask[row, column] = 1
        return {"input_ids": ids, "attention_mask": mask}


class _FakeModel:
    """Each token's state is its character code repeated; padding is zero."""

    calls: int = 0

    def __call__(self, input_ids: object, attention_mask: object) -> object:
        import torch

        _FakeModel.calls += 1
        ids = input_ids
        assert isinstance(ids, torch.Tensor)
        states = ids.to(torch.float32).unsqueeze(-1).repeat(1, 1, 4)

        class _Output:
            last_hidden_state = states

        return _Output()


def test_backend_pool_and_encode_agree_and_restore_input_order() -> None:
    """Sub-batching by length must not reorder the results a caller gets."""
    from research_agent.models.backend import TransformersDeviceBackend
    from research_agent.models.embedding import mean_pool_unit_l2

    _FakeModel.calls = 0
    backend = TransformersDeviceBackend(
        _FakeTokenizer(), _FakeModel(), "cpu", sub_batch=2
    )
    texts = ["ccccc", "a", "bbbbbbbbb", "dd"]
    encodings = backend.encode(texts)
    assert [encoding.token_count for encoding in encodings] == [5, 1, 9, 2]
    assert _FakeModel.calls == 2, "four texts in sub-batches of two is two passes"
    pooled = backend.pool(texts)
    assert len(pooled) == 4
    for encoding, vector in zip(encodings, pooled, strict=True):
        expected = mean_pool_unit_l2(encoding, 4)
        assert max(abs(a - b) for a, b in zip(vector, expected, strict=True)) <= 1e-6
    # every vector is the unit direction of its own character code: order kept
    assert pooled[1] == pytest.approx(pooled[0])  # both constant rows normalize alike
    assert backend.pool([]) == ()


def test_backend_refuses_a_text_over_the_token_budget_before_any_forward_pass() -> None:
    from research_agent.models.backend import TransformersDeviceBackend
    from research_agent.models.embedding import TokenBudgetExceededError
    from research_agent.models.manifest import MAX_MODEL_TOKENS

    _FakeModel.calls = 0
    backend = TransformersDeviceBackend(_FakeTokenizer(), _FakeModel(), "cpu")
    with pytest.raises(TokenBudgetExceededError):
        backend.pool(["x" * (MAX_MODEL_TOKENS + 1), "ok"])
    assert _FakeModel.calls == 0
