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
