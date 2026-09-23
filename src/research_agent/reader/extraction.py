"""No optical character recognition among a container image's pinned inputs.

SDD-MD-10: no component loads or calls an optical character recognition
model. Extraction is limited to non-executing source parsing, PDF text-layer
reading and page rendering (``reader/extract.py``, ``reader/media.py``);
`validate_extraction_policy` checks an image's pinned inputs, its locked
Python packages, its model identities and its configured extractors, against
that limit before the image is run.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass

from ..contracts.primitives import ContractValidationError

__all__ = [
    "ALLOWED_EXTRACTORS",
    "ExtractionPolicyError",
    "ImageInputs",
    "locked_packages",
    "validate_extraction_policy",
]

# The only extraction methods the launch profile admits (TDD-4.1.71).
ALLOWED_EXTRACTORS: frozenset[str] = frozenset(
    {"latex_source", "pdf_text_layer", "page_render"}
)

# Recognition engines and models whose names do not start or end with "ocr".
_OCR_NAMES: frozenset[str] = frozenset(
    {
        "doctr",
        "python-doctr",
        "donut",
        "kraken",
        "nougat",
        "pix2tex",
        "surya",
        "tesseract",
        "trocr",
    }
)
_NAME_SEPARATORS = re.compile(r"[-_./:@]+")


class ExtractionPolicyError(ContractValidationError):
    """An image's pinned inputs include optical character recognition.

    ``findings`` lists every offending input so the refusal can be recorded
    whole.
    """

    def __init__(self, findings: tuple[str, ...]) -> None:
        super().__init__(
            "image inputs include optical character recognition: " + ", ".join(findings)
        )
        self.findings = findings


@dataclass(frozen=True, slots=True)
class ImageInputs:
    """The pinned inputs of one container image (SDD-PL-06)."""

    packages: tuple[str, ...]
    model_ids: tuple[str, ...]
    extractors: tuple[str, ...]


def locked_packages(lock_file: bytes) -> tuple[str, ...]:
    """The package names a uv lock file pins, in lock order."""

    lock = tomllib.loads(lock_file.decode("utf-8"))
    return tuple(str(package["name"]) for package in lock.get("package", ()))


def _is_ocr(name: str) -> bool:
    lowered = name.lower()
    if lowered in _OCR_NAMES:
        return True
    tokens = [token for token in _NAME_SEPARATORS.split(lowered) if token]
    return any(
        token.startswith("ocr")
        or token.endswith("ocr")
        or "tesser" in token
        or token in _OCR_NAMES
        for token in tokens
    )


def _ocr_findings(kind: str, names: Iterable[str]) -> list[str]:
    return [f"{kind} {name}" for name in names if _is_ocr(name)]


def validate_extraction_policy(inputs: ImageInputs) -> None:
    """Raise ``ExtractionPolicyError`` if *inputs* admit any recognition path.

    A locked package or model identity naming a recognition engine, or a
    configured extractor outside ``ALLOWED_EXTRACTORS`` (an external
    recognition endpoint among them), is a finding. An image with findings
    is not run (SDD-MD-10).
    """

    findings = _ocr_findings("package", inputs.packages)
    findings += _ocr_findings("model", inputs.model_ids)
    findings += [
        f"extractor {name}"
        for name in inputs.extractors
        if name not in ALLOWED_EXTRACTORS
    ]
    if findings:
        raise ExtractionPolicyError(tuple(findings))
