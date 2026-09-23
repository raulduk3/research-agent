"""Authoritative record kinds accepted only from their one writer role (SDD-SR-04).

A language model's output can populate a proposal -- a forecast, a mutation --
or a source observation carried in with proxy provenance, but storage accepts
a resolution, a score or an exclusion record only from the resolver, scorer or
operator role that computed it. `AuthorityPolicy.permitted` checks the
caller's authenticated role against the record kind; it never reads a role an
agent, or any other untrusted caller, could write into a submitted payload.
"""

from __future__ import annotations

from .primitives import ContractValidationError

_WRITER_ROLES: dict[str, frozenset[str]] = {
    "proposal": frozenset({"agent", "resolver", "scorer", "operator"}),
    "source_observation": frozenset({"ingest", "operator"}),
    "resolution": frozenset({"resolver", "operator"}),
    "score": frozenset({"scorer", "operator"}),
    "exclusion_record": frozenset({"scorer", "resolver", "operator"}),
}

AUTHORITATIVE_RECORD_KINDS: frozenset[str] = frozenset(_WRITER_ROLES)


class AuthorityPolicy:
    """Restrict each authoritative record kind to the role that may write it.

    A resolution, a score and an exclusion record settle something; nothing
    an agent model outputs, including a Jev assessment, satisfies them,
    whatever role field it carries. A proposal is the one kind an agent may
    write, and a source observation is ingest's alone.
    """

    def permitted(self, *, record_kind: str, writer_role: str) -> bool:
        allowed = _WRITER_ROLES.get(record_kind)
        if allowed is None:
            raise ContractValidationError(
                "record_kind is not a recognized authoritative record"
            )
        return writer_role in allowed
