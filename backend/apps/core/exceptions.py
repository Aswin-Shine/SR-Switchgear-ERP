"""The domain exception hierarchy.

Services raise these. Views never build an HTTP response from a database error
directly; ``apps.core.middleware.DomainErrorMiddleware`` maps this hierarchy to
status codes so the mapping lives in exactly one place.

BACKEND_PLAN.md section 4:
    PermissionDenied -> 403, RuleViolation -> 422, StaleTransition -> 409.
"""


class DomainError(Exception):
    """Base class. Carries a message and an optional machine-readable code."""

    status_code = 400
    default_code = "domain_error"

    def __init__(self, message: str = "", code: str = "", **context):
        self.message = message or self.__class__.__doc__ or "Domain error"
        self.code = code or self.default_code
        self.context = context
        super().__init__(self.message)


class PermissionDenied(DomainError):
    """The actor is not permitted to do this."""

    status_code = 403
    default_code = "permission_denied"


class RuleViolation(DomainError):
    """The request is well-formed but breaks a business rule."""

    status_code = 422
    default_code = "rule_violation"


class StaleTransition(DomainError):
    """Someone else moved this job line first.

    Raised when ``pipeline.apply_transition()`` rejects an insert whose
    ``from_stage_id`` no longer matches the line's real current stage. The
    trigger is the arbiter; this is its Python face.
    """

    status_code = 409
    default_code = "stale_transition"


class ConfigurationError(DomainError):
    """Seed data is self-contradictory and no user action can fix it.

    The schema's ``UNIQUE (from_stage_id, action_code, allowed_role_id)``
    permits two rules that agree on the key but disagree on ``to_stage_id``
    across different roles. Nothing else catches that, so Phase 4 raises this.
    """

    status_code = 500
    default_code = "configuration_error"


class NotFound(DomainError):
    """The object does not exist, or is soft-deleted, or is invisible to the actor."""

    status_code = 404
    default_code = "not_found"
