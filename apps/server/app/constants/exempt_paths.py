"""The exact paths that individual guards do not apply to.

Every exemption is a full path compared for equality, never a prefix. A prefix match would exempt
more than it names: `/health/ready-not-really` and `/v1/billing/webhook-spoof` both begin with an
exempt path, and under prefix matching an attacker could reach a guarded handler by mounting it
below one. The CSRF guard's tests assert exactly that pair, so the equality comparison is pinned
rather than assumed.
"""

# Liveness and readiness answer no state-changing method and hold nothing a forged request could
# reach; keeping them exempt means an orchestrator's probe never needs the browser header.
HEALTH_PATHS = frozenset({"/health", "/health/ready"})
# Stripe cannot send `X-Requested-With`, and the webhook is authenticated by its signature instead.
STRIPE_WEBHOOK_PATH = "/v1/billing/webhook"

CSRF_EXEMPT_PATHS = frozenset(HEALTH_PATHS | {STRIPE_WEBHOOK_PATH})
