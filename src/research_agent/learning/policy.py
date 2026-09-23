"""Training-ancestry gate for any proposed neural-weight training job (SDD-MD-02).

The system never trains a model from weights it initialized itself. This
module validates that ancestry claim before a training job is created, then
refuses the job anyway: no admitted job kind is enabled at launch, so passing
ancestry validation never becomes permission to run. The three numeric
logistic prediction heads (SDD-FT-08) are not neural-weight training and
carry an explicit fitting exemption from the whole gate.
"""

from __future__ import annotations

from dataclasses import dataclass

from research_agent.contracts.primitives import (
    validate_non_empty_string,
    validate_sha256,
)

# The only job kind SDD-FT-08 fits: a numeric logistic prediction head, which
# starts from zero-initialized coefficients (SDD-FT-08's own fixed objective),
# never from borrowed neural weights, and so falls outside MD-02 entirely.
FITTING_EXEMPT_JOB_KINDS: frozenset[str] = frozenset({"prediction_head_fit"})


class TrainingOriginError(ValueError):
    """A proposed training job has no admissible ancestry, or is disabled at launch."""


@dataclass(frozen=True, slots=True)
class TrainingJobProposal:
    """One proposed training job, named by kind, with its claimed ancestry.

    ``published_weights_hash`` and ``parent_chain`` describe the checkpoint
    the job would start from: the published artifact and the ordered chain of
    checkpoint hashes descending from it to the immediate starting point. An
    exempt job kind carries no ancestry requirement and both fields are
    ignored.
    """

    job_kind: str
    published_weights_hash: str | None
    parent_chain: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_non_empty_string(self.job_kind)
        if not isinstance(self.parent_chain, tuple):
            raise TrainingOriginError(
                "a training job's parent chain must be an immutable tuple"
            )
        if self.job_kind in FITTING_EXEMPT_JOB_KINDS:
            return
        if self.published_weights_hash is not None:
            validate_sha256(self.published_weights_hash)
        for value in self.parent_chain:
            validate_sha256(value)


def validate_training_origin(proposal: TrainingJobProposal) -> None:
    """Raise ``TrainingOriginError`` unless the proposal is fitting-exempt.

    A fitting-exempt proposal (a prediction-head fit) returns without any
    ancestry check: it trains no neural weights and MD-02 does not apply. Any
    other proposal is validated against a published-weight artifact and a
    nonempty parent chain first, so an absent ancestry claim is refused
    before job creation rather than after a checkpoint starts writing; a
    proposal that does carry verifiable ancestry is refused anyway, because
    no non-exempt training job kind is admitted at launch (SDD-MD-02).
    """

    if proposal.job_kind in FITTING_EXEMPT_JOB_KINDS:
        return
    if proposal.published_weights_hash is None or not proposal.parent_chain:
        raise TrainingOriginError(
            "a neural-weight training job requires a published-weight artifact "
            "and a verifiable parent chain"
        )
    raise TrainingOriginError(
        "neural-weight training jobs are disabled at launch (SDD-MD-02)"
    )
