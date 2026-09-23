"""Pure statistics over already-fetched records: no clock, RNG seed excepted, no storage."""

from __future__ import annotations


class MeasurementError(ValueError):
    """Raised when a measurement function's input violates its pure contract."""
