"""Stable failures raised by the storage transaction core."""


class StorageError(Exception):
    """Base class for a storage failure safe to classify at an API boundary."""


class IntegrityFailure(StorageError):
    """Stored or supplied bytes do not match their content identity."""


class IdempotencyConflict(StorageError):
    """A command or idempotency key was reused for different content."""


class StateConflict(StorageError):
    """The requested state transition is not valid."""


class StaleLease(StorageError):
    """A worker attempted to write through a superseded lease epoch."""


class LeaseExpired(StorageError):
    """A worker attempted to write after its lease expired."""


class UnavailableInput(StorageError):
    """A referenced committed input is absent or unavailable."""


class TransactionUnavailable(StorageError):
    """A serializable transaction could not complete within the retry bound."""
