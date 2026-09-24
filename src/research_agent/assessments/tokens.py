"""A request token counter calibrated against the provider's own accounting.

Measured 2026-09-23 against the gateway's ``usage.input_tokens`` (see
``docs/evidence/models/jev-smoke-2026-09-23.md``): English prose costs about
4.5 characters per token plus about 314 tokens of question overhead, and real
papers -- mathematics, code, tables -- cost 2.95 characters per token. The
counter here charges 2.5 characters per token, which over-counts every
observed input, so a request it admits fits the provider's limit.
"""

from __future__ import annotations

import math

CHARS_PER_TOKEN = 2.5
QUESTION_OVERHEAD_TOKENS = 314


class CalibratedCounter:
    """Conservative token count from character length; see the module note."""

    def count(self, text: str) -> int:
        return math.ceil(len(text) / CHARS_PER_TOKEN)
