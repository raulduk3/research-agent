"""Atomic per-island digest publication and rater-bound access (EN-32)."""

from __future__ import annotations

from dataclasses import dataclass

from .build import ENTRY_LIMIT, DigestManifest

ISLAND_READERS: dict[str, str | None] = {
    "cs": "cs_rater",
    "quant-ph": "quant_ph_rater",
    "q-bio": None,
}


class DigestAccessRefused(Exception):
    """Raised when an identity may not read a published digest."""


@dataclass(frozen=True, slots=True)
class DigestPublication:
    """One island's committed digest: its content-addressed id and bound reader."""

    digest_id: str
    manifest: DigestManifest
    readable_by: str | None

    def read(self, *, identity: str | None) -> DigestManifest:
        """Return the manifest for the exact bound rater identity, or refuse.

        The q-bio digest has ``readable_by=None`` and is refused for every
        identity, including an operator identity: it is built, scored and
        stored, and delivered to no one (EN-32).
        """

        if self.readable_by is None or identity != self.readable_by:
            raise DigestAccessRefused("identity may not read this digest")
        return self.manifest


def publish_digest(manifest: DigestManifest) -> DigestPublication:
    """Commit one island's complete manifest and bind it to its rater identity.

    Refuses a manifest naming an island outside the three seeded islands, or
    exceeding the twelve-entry cap, so an incomplete or malformed build can
    never become a readable publication: no partially populated digest
    becomes visible (TDD-3.1.31).
    """

    if manifest.island not in ISLAND_READERS:
        raise ValueError(f"unknown island: {manifest.island!r}")
    if len(manifest.entries) > ENTRY_LIMIT:
        raise ValueError("digest exceeds the twelve-entry cap")
    return DigestPublication(
        digest_id=manifest.digest_hash,
        manifest=manifest,
        readable_by=ISLAND_READERS[manifest.island],
    )
