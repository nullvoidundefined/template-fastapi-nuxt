"""Machine-readable error codes; clients switch on these, never on the message.

A code is part of the API contract, so every code any handler, middleware, or service answers
with is registered here rather than written as a literal at the call site. Each member's value is
its own name, which is what makes the registry and the wire impossible to drift apart, and
`StrEnum` means `json.dumps` writes the bare string rather than an enum repr.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Every error code this application answers with, namespaced DOMAIN_REASON."""

    # The signed-in user is not an administrator (slice 05).
    AUTH_ADMIN_REQUIRED = "AUTH_ADMIN_REQUIRED"
    # The email and password pair did not match a user (slice 03).
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    # The route needs a session and the request carried none (slice 03).
    AUTH_REQUIRED = "AUTH_REQUIRED"
    # The session cookie names a session that has expired (slice 03).
    AUTH_SESSION_EXPIRED = "AUTH_SESSION_EXPIRED"
    # Registration was attempted for an address an account already uses (slice 03).
    AUTH_EMAIL_ALREADY_REGISTERED = "AUTH_EMAIL_ALREADY_REGISTERED"
    # A password-reset token is unknown, already used, expired, or superseded (slice 04).
    AUTH_RESET_TOKEN_INVALID = "AUTH_RESET_TOKEN_INVALID"  # noqa: S105 (a code, not a secret)
    # The portal was requested by a user with no Stripe customer yet (slice 06).
    BILLING_NO_ACCOUNT = "BILLING_NO_ACCOUNT"
    # A billing route was called on a deployment with no STRIPE_SECRET_KEY (slice 06).
    BILLING_NOT_CONFIGURED = "BILLING_NOT_CONFIGURED"
    # A webhook arrived without a Stripe-Signature header, or with no signing secret set (slice 06).
    BILLING_WEBHOOK_MISCONFIGURED = "BILLING_WEBHOOK_MISCONFIGURED"
    # A webhook's signature did not verify against the signing secret (slice 06).
    BILLING_WEBHOOK_INVALID_SIGNATURE = "BILLING_WEBHOOK_INVALID_SIGNATURE"
    # Another delivery of the same event holds a claim younger than ten minutes; retry (slice 06).
    BILLING_WEBHOOK_IN_PROGRESS = "BILLING_WEBHOOK_IN_PROGRESS"
    # A verified webhook's handler raised; the event is marked failed for a retry (slice 06).
    BILLING_WEBHOOK_PROCESSING_FAILED = "BILLING_WEBHOOK_PROCESSING_FAILED"
    # A state-changing request arrived without X-Requested-With (slice 02, PR 4).
    CSRF_HEADER_MISSING = "CSRF_HEADER_MISSING"
    # Another request holding the same Idempotency-Key is still running (slice 05).
    IDEMPOTENCY_KEY_IN_PROGRESS = "IDEMPOTENCY_KEY_IN_PROGRESS"
    # An Idempotency-Key was reused for a different method, path, or body (slice 05).
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    # The request body exceeded the 100 KB limit, rejected before the route ran.
    INPUT_PAYLOAD_TOO_LARGE = "INPUT_PAYLOAD_TOO_LARGE"
    # The request body failed schema validation.
    INPUT_VALIDATION_ERROR = "INPUT_VALIDATION_ERROR"
    # The client exceeded one of the two rate-limit buckets (slice 02, PR 5).
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    # The path exists but not for this method.
    ROUTING_METHOD_NOT_ALLOWED = "ROUTING_METHOD_NOT_ALLOWED"
    # No route matched the request path.
    ROUTING_NOT_FOUND = "ROUTING_NOT_FOUND"
    # The database could not be reached while handling the request.
    SERVER_DATABASE_UNAVAILABLE = "SERVER_DATABASE_UNAVAILABLE"
    # An unexpected exception reached the outermost handler.
    SERVER_INTERNAL_ERROR = "SERVER_INTERNAL_ERROR"
    # Redis is unreachable in production, so an auth route fails closed (slice 02, PR 5).
    SERVER_RATE_LIMIT_UNAVAILABLE = "SERVER_RATE_LIMIT_UNAVAILABLE"
    # The handler ran past the 30-second timeout (slice 02, PR 4).
    SERVER_REQUEST_TIMEOUT = "SERVER_REQUEST_TIMEOUT"
    # POST /v1/uploads was called on a deployment with no R2 bucket configured (slice 07).
    UPLOADS_STORAGE_UNCONFIGURED = "UPLOADS_STORAGE_UNCONFIGURED"
