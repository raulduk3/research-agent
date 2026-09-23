"""Permission registry gate: refuse an outbound fetch before it is built.

Every source ingest requests from is reviewed once, in
``docs/evidence/source-pilot/access-rules.md``, and that review names the
exact hosts the license and terms of use cover. A source that offers content
only behind a paywall gets no such record. This module is the single place
that answers "is this destination reviewed and permitted", so a fetch to any
other address is refused before a connection is opened, and a redirect is
checked against the identical policy before it would ever be followed.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


class SourceNotPermitted(Exception):
    """A destination has no reviewed, permitted source record."""


@dataclass(frozen=True, slots=True)
class PermittedSource:
    hosts: frozenset[str]
    license_reviewed: bool


# Mirrors docs/evidence/source-pilot/access-rules.md: the sources this ingest
# job uses, each with the exact hosts that review covers. Adding a host or
# source here without updating that review file is a policy error, not a
# code change to make lightly.
REGISTRY: dict[str, PermittedSource] = {
    "arxiv": PermittedSource(frozenset({"oaipmh.arxiv.org", "export.arxiv.org"}), True),
    "arxiv_gcs_pdf": PermittedSource(frozenset({"storage.googleapis.com"}), True),
    "openalex": PermittedSource(frozenset({"api.openalex.org"}), True),
}


def authorize_fetch(source: str, host: str) -> None:
    """Raise unless `source` names a reviewed adapter permitted to reach `host`.

    Called before any request is built; a refusal here means no connection is
    ever opened.
    """
    entry = REGISTRY.get(source)
    if entry is None or not entry.license_reviewed or host not in entry.hosts:
        raise SourceNotPermitted(
            f"{source!r} via {host!r} is not a reviewed permitted source"
        )


def authorize_redirect(source: str, location: str) -> None:
    """Raise unless a redirect's target is covered by the same source policy.

    A paywall or auth challenge answers with a redirect to an unreviewed
    route; this is the check that must pass before such a redirect is ever
    followed. No browser fallback, proxy or scraped mirror is a permitted
    target regardless of what it redirects to.
    """
    parsed = urlsplit(location)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SourceNotPermitted("redirect target is not a well-formed https url")
    authorize_fetch(source, parsed.hostname)
