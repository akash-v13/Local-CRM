"""Domain errors.

Services raise these; the API layer (`app/main.py`) turns them into HTTP
responses. Keeping them HTTP-free means the same services can be called from
the worker or a CLI.
"""


class DomainError(Exception):
    """Base class for all expected, user-facing errors."""


class NotFoundError(DomainError):
    """The requested record does not exist (or belongs to another tenant). → 404"""


class InvalidTransitionError(DomainError):
    """A case status change is not allowed by the lifecycle. → 409"""


class CaseClosedError(DomainError):
    """The case is closed and no longer accepts replies. → 409"""


class RoutingError(DomainError):
    """Automatic routing or a reroute isn't possible for this case/queue. → 409"""


class ConflictError(DomainError):
    """Someone else changed the record first (stale version). → 409"""
