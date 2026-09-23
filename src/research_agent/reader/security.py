"""Wrap paper-sourced content as explicit, data-only untrusted evidence (IN-23).

Text retrieved from a paper is data the agent model reads, never an
instruction. ``SourceEvidence`` is the one shape a tool response uses to
carry it: a closed, explicitly-untrusted envelope that cannot masquerade
as a system or developer message or a tool definition, however it is
formatted inside. Nothing here grants authority; tool dispatch validates a
run's own capability, snapshot and budgets independently on every call
regardless of what a source's text claims (SR-05, AG-10, AG-12).
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from ..contracts.passages import SourceLocator
from ..contracts.primitives import ContractValidationError, validate_non_empty_string

_KINDS = frozenset({"text", "locator", "image_reference"})


def escape_markup(text: str) -> str:
    """Escape HTML/Markdown-significant characters in untrusted source text.

    Applied before any rendered (non-JSON-data) surface displays a source
    span, so embedded markup cannot restyle or hide content for a human
    reader. It does not change what the agent model receives through the
    data-only tool-result channel; strict tool dispatch is what keeps that
    channel from being read as instructions.
    """

    return html.escape(text, quote=True)


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    """One untrusted span of paper content, tagged data-only and never authoritative.

    Exactly one of ``text``, ``locator`` or ``image_reference`` is
    populated, matching ``kind``; the other two are ``None``. Constructing
    one with ``untrusted=False`` is refused outright, so no code path can
    silently promote source content to a trusted instruction by omitting
    the marker.
    """

    kind: str
    text: str | None
    locator: SourceLocator | None
    image_reference: str | None
    untrusted: bool = True

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ContractValidationError(
                "SourceEvidence.kind is not an admitted value"
            )
        if not self.untrusted:
            raise ContractValidationError("SourceEvidence must be marked untrusted")
        fields = (self.text, self.locator, self.image_reference)
        if sum(field is not None for field in fields) != 1:
            raise ContractValidationError(
                "SourceEvidence carries exactly one payload matching its kind"
            )
        if self.kind == "text":
            if self.text is None:
                raise ContractValidationError("a text SourceEvidence requires text")
            validate_non_empty_string(self.text)
        elif self.kind == "locator":
            if not isinstance(self.locator, SourceLocator):
                raise ContractValidationError(
                    "a locator SourceEvidence requires a SourceLocator"
                )
        elif self.image_reference is None or not isinstance(self.image_reference, str):
            raise ContractValidationError(
                "an image_reference SourceEvidence requires a hash string"
            )

    def to_dict(self) -> dict[str, object]:
        """The explicit data-only envelope a tool response carries (IN-23).

        This is a plain JSON object under a tool-result payload, never a
        message role and never a tool schema; nothing here is eligible to
        be read back as an instruction by the harness that assembles the
        agent's conversation.
        """

        return {
            "kind": self.kind,
            "text": self.text,
            "locator": self.locator.to_dict() if self.locator is not None else None,
            "image_reference": self.image_reference,
            "untrusted": self.untrusted,
        }

    @classmethod
    def of_text(cls, text: str) -> "SourceEvidence":
        return cls("text", text, None, None)

    @classmethod
    def of_locator(cls, locator: SourceLocator) -> "SourceEvidence":
        return cls("locator", None, locator, None)

    @classmethod
    def of_image_reference(cls, image_reference: str) -> "SourceEvidence":
        return cls("image_reference", None, None, image_reference)
