"""Provides a route the generation of the idempotency claim its request holds, or None.

The `Idempotency-Key` middleware leaves it in the request state when it claims or takes over a
key. A route that calls a provider with its own idempotency layer derives that provider's key
from it (IAN-373): the value repeats when a takeover reruns the handler after a crash, and is new
once a failed attempt released its claim, so the provider replays exactly the calls that already
succeeded. It is None for a request without a key, or one the middleware did not claim.
"""

from typing import Annotated

from fastapi import Depends, Request

from app.constants.idempotency import CLAIM_GENERATION_STATE_KEY


def get_idempotency_claim_generation(request: Request) -> str | None:
    """Return the claim generation the middleware bound to this request, when it bound one."""
    generation = getattr(request.state, CLAIM_GENERATION_STATE_KEY, None)
    return generation if isinstance(generation, str) else None


IdempotencyClaimGeneration = Annotated[str | None, Depends(get_idempotency_claim_generation)]
