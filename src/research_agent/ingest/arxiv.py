"""Bounded arXiv OAI-PMH listing and original-version document requests."""

from __future__ import annotations

import re
import ssl
import unicodedata
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

from research_agent.ingest.fetch import BoundedResponse, bounded_get

OAI_HOST = "oaipmh.arxiv.org"
DOCUMENT_HOST = "export.arxiv.org"
# arXiv's terms: one request every three seconds on a single connection.
MINIMUM_INTERVAL_SECONDS = 3.0
TARGET_SETS = ("cs:cs:AI", "cs:cs:LG")
TARGET_CATEGORIES = frozenset({"cs.AI", "cs.LG"})
# Each category keeps its own subject-level OAI set rather than collapsing
# into its archive: an archive-level listing only carries papers whose
# *primary* category is in that archive, silently dropping a paper
# cross-listed in from elsewhere that a subject set still carries.
_CATEGORY_SETS: dict[str, str] = {
    "cs.AI": "cs:cs:AI",
    "cs.LG": "cs:cs:LG",
    "quant-ph": "physics:quant-ph",
    "q-bio": "q-bio",
}
_ALL_TARGET_SETS = frozenset(_CATEGORY_SETS.values())
_OAI_MAX_BYTES = 64 * 1024 * 1024
_DOCUMENT_MAX_BYTES = 64 * 1024 * 1024
_TIMEOUT_SECONDS = 120.0
_OAI = "{http://www.openarchives.org/OAI/2.0/}"
_RAW = "{http://arxiv.org/OAI/arXivRaw/}"
_FAMILY = re.compile(r"[0-9]{4}\.[0-9]{4,5}\Z")
# Pre-2007 identifiers such as math/0510276 still appear when old records change.
_LEGACY_FAMILY = re.compile(r"[a-z-]+(?:\.[A-Z]{2})?/[0-9]{7}\Z")
_CATEGORY = re.compile(r"[a-z-]+(?:\.[A-Za-z-]+)?\Z")
_VERSION = re.compile(r"v([1-9][0-9]*)\Z")
_TOKEN = re.compile(r"[\x21-\x7e]{1,4096}\Z")
# arXivRaw joins authors with ", " and joins the final name with " and ",
# sometimes with no comma at all when there are exactly two; splitting on
# either separator, independent of how many "and"s appear, counts names
# rather than assuming one final-name convention (#149).
_AUTHOR_SEPARATOR = re.compile(r",\s*| and ")


class ArxivFormatError(ValueError):
    """A retained arXiv response is not the closed shape this adapter accepts."""


@dataclass(frozen=True, slots=True)
class ArxivVersion:
    number: int
    submitted_at: str


@dataclass(frozen=True, slots=True)
class ArxivListing:
    """One arXivRaw record exactly as retained; no field is inferred."""

    family_id: str
    datestamp: str
    categories: tuple[str, ...]
    versions: tuple[ArxivVersion, ...]
    title: str
    abstract: str
    license_url: str | None
    doi: str | None
    authors: str

    @property
    def first_public_at(self) -> str:
        # v1 submission time; announcement can follow by a few days.
        return self.versions[0].submitted_at

    @property
    def author_count(self) -> int:
        return len(
            [part for part in _AUTHOR_SEPARATOR.split(self.authors) if part.strip()]
        )

    @property
    def legacy_identifier(self) -> bool:
        """Old-style ids were retired in April 2007, before any pilot month."""
        return _FAMILY.fullmatch(self.family_id) is None

    @property
    def in_target_categories(self) -> bool:
        return not TARGET_CATEGORIES.isdisjoint(self.categories)


@dataclass(frozen=True, slots=True)
class OaiPage:
    records: tuple[ArxivListing, ...]
    resumption_token: str | None
    complete_list_size: int | None


def target_sets(categories: Iterable[str]) -> tuple[str, ...]:
    """The OAI-PMH sets that together enumerate every configured category, in
    first-seen order, deduplicated."""
    sets: list[str] = []
    for category in categories:
        try:
            set_spec = _CATEGORY_SETS[category]
        except KeyError:
            raise ValueError(f"unsupported corpus category: {category}") from None
        if set_spec not in sets:
            sets.append(set_spec)
    return tuple(sets)


def listing_path(
    *, set_spec: str, from_date: str, until_date: str, token: str | None
) -> str:
    """Closed ListRecords query: a first page or its exact continuation."""
    if token is not None:
        if not isinstance(token, str) or _TOKEN.fullmatch(token) is None:
            raise ValueError("resumption token is invalid")
        return "/oai?" + urlencode({"verb": "ListRecords", "resumptionToken": token})
    if set_spec not in _ALL_TARGET_SETS:
        raise ValueError("set is not an admitted target category")
    first, last = date.fromisoformat(from_date), date.fromisoformat(until_date)
    if first.isoformat() != from_date or last.isoformat() != until_date:
        raise ValueError("listing dates must be canonical YYYY-MM-DD")
    if first > last:
        raise ValueError("listing dates are out of order")
    return "/oai?" + urlencode(
        {
            "verb": "ListRecords",
            "metadataPrefix": "arXivRaw",
            "set": set_spec,
            "from": from_date,
            "until": until_date,
        }
    )


def document_path(family_id: str, kind: str) -> str:
    """The original v1 source archive or PDF; later versions are never requested."""
    if _FAMILY.fullmatch(family_id) is None:
        raise ValueError("arXiv family id must be a canonical unversioned id")
    if kind not in {"src", "pdf"}:
        raise ValueError("document kind must be src or pdf")
    return f"/{kind}/{family_id}v1"


def fetch_listing_page(
    path: str,
    *,
    host: str = OAI_HOST,
    port: int = 443,
    context: ssl.SSLContext | None = None,
) -> BoundedResponse:
    return bounded_get(
        host,
        port,
        path,
        context=ssl.create_default_context() if context is None else context,
        accept="text/xml",
        max_bytes=_OAI_MAX_BYTES,
        timeout_seconds=_TIMEOUT_SECONDS,
    )


def fetch_document(
    path: str,
    *,
    host: str = DOCUMENT_HOST,
    port: int = 443,
    context: ssl.SSLContext | None = None,
) -> BoundedResponse:
    return bounded_get(
        host,
        port,
        path,
        context=ssl.create_default_context() if context is None else context,
        accept="*/*",
        max_bytes=_DOCUMENT_MAX_BYTES,
        timeout_seconds=_TIMEOUT_SECONDS,
    )


def _text(parent: ElementTree.Element, name: str, *, required: bool) -> str | None:
    found = parent.findall(_RAW + name)
    if len(found) > 1:
        raise ArxivFormatError(f"arXivRaw {name} is repeated")
    if not found or found[0].text is None or not found[0].text.strip():
        if required:
            raise ArxivFormatError(f"arXivRaw {name} is missing")
        return None
    value = unicodedata.normalize("NFC", found[0].text)
    return " ".join(value.split())


def _utc(value: str) -> str:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError) as error:
        raise ArxivFormatError("version date is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ArxivFormatError("version date has no zone")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _record(record: ElementTree.Element) -> ArxivListing | None:
    header = record.find(_OAI + "header")
    if header is None:
        raise ArxivFormatError("record header is missing")
    if header.get("status") == "deleted":
        return None
    datestamp = header.findtext(_OAI + "datestamp")
    raw = record.find(f"{_OAI}metadata/{_RAW}arXivRaw")
    if datestamp is None or raw is None:
        raise ArxivFormatError("record datestamp or arXivRaw metadata is missing")
    family_id = _text(raw, "id", required=True)
    assert family_id is not None
    if (
        _FAMILY.fullmatch(family_id) is None
        and _LEGACY_FAMILY.fullmatch(family_id) is None
    ):
        raise ArxivFormatError("record id is not a canonical arXiv id")
    categories = tuple((_text(raw, "categories", required=True) or "").split())
    if (
        not categories
        or len(set(categories)) != len(categories)
        or any(_CATEGORY.fullmatch(value) is None for value in categories)
    ):
        raise ArxivFormatError("record categories are invalid")
    versions = []
    for element in raw.findall(_RAW + "version"):
        match = _VERSION.fullmatch(element.get("version", ""))
        submitted = element.findtext(_RAW + "date")
        if match is None or submitted is None:
            raise ArxivFormatError("record version is invalid")
        versions.append(ArxivVersion(int(match.group(1)), _utc(submitted)))
    if not versions or [version.number for version in versions] != list(
        range(1, len(versions) + 1)
    ):
        raise ArxivFormatError("record versions are not v1..vN in order")
    title = _text(raw, "title", required=True)
    abstract = _text(raw, "abstract", required=True)
    authors = _text(raw, "authors", required=True)
    assert title is not None and abstract is not None and authors is not None
    return ArxivListing(
        family_id,
        date.fromisoformat(datestamp.strip()).isoformat(),
        categories,
        tuple(versions),
        title,
        abstract,
        _text(raw, "license", required=False),
        _text(raw, "doi", required=False),
        authors,
    )


def parse_listing_page(raw: bytes) -> OaiPage:
    """Parse one whole retained page, or reject all of it."""
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ArxivFormatError("document type declarations are refused")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as error:
        raise ArxivFormatError("OAI response is not well-formed XML") from error
    if root.tag != _OAI + "OAI-PMH":
        raise ArxivFormatError("response is not an OAI-PMH envelope")
    oai_error = root.find(_OAI + "error")
    if oai_error is not None:
        if oai_error.get("code") == "noRecordsMatch":
            return OaiPage((), None, 0)
        raise ArxivFormatError(f"OAI error {oai_error.get('code')}")
    listing = root.find(_OAI + "ListRecords")
    if listing is None:
        raise ArxivFormatError("ListRecords is missing")
    records = []
    for element in listing.findall(_OAI + "record"):
        parsed = _record(element)
        if parsed is not None:
            records.append(parsed)
    token_element = listing.find(_OAI + "resumptionToken")
    token = None
    size = None
    if token_element is not None:
        token = (token_element.text or "").strip() or None
        if token is not None and _TOKEN.fullmatch(token) is None:
            raise ArxivFormatError("resumption token is invalid")
        declared = token_element.get("completeListSize")
        if declared is not None:
            if not declared.isdigit():
                raise ArxivFormatError("completeListSize is invalid")
            size = int(declared)
    return OaiPage(tuple(records), token, size)


def listing_window(months: tuple[str, ...], frozen_at: str) -> tuple[str, str]:
    """Datestamps are last-modified dates, so harvest from the first month to the
    freeze: every paper first submitted in the window was modified on or after it."""
    if not months:
        raise ValueError("no publication months")
    first = date.fromisoformat(months[0] + "-01")
    freeze = datetime.fromisoformat(frozen_at.replace("Z", "+00:00")).date()
    return first.isoformat(), freeze.isoformat()
