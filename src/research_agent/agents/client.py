"""The pinned agent model client's earlier module path.

The owner is :mod:`research_agent.agents.model_client` (TDD-4.1.74). This
module only re-exports it for callers that still import the earlier path,
and adds no behavior of its own.
"""

from __future__ import annotations

from research_agent.agents.model_client import (
    AGENT_MODEL_ID,
    AGENT_PROVIDER,
    REPETITION_PENALTY,
    SAMPLING_DOMAIN,
    TEMPERATURE,
    TOP_P,
    UNPINNED_REVISION,
    AgentDeploymentManifest,
    ChatCompletionsTransport,
    DeploymentDrift,
    DeploymentUnqualified,
    InferenceOnlyClient,
    TurnUsage,
    derive_request_seed,
)

#: The earlier name of :class:`InferenceOnlyClient`.
PinnedModelClient = InferenceOnlyClient

__all__ = [
    "AGENT_PROVIDER",
    "AGENT_MODEL_ID",
    "UNPINNED_REVISION",
    "SAMPLING_DOMAIN",
    "TEMPERATURE",
    "TOP_P",
    "REPETITION_PENALTY",
    "DeploymentDrift",
    "DeploymentUnqualified",
    "AgentDeploymentManifest",
    "ChatCompletionsTransport",
    "TurnUsage",
    "PinnedModelClient",
    "InferenceOnlyClient",
    "derive_request_seed",
]
