"""The bounds of an idempotency claim: which requests take one, how long a lease and a replay last.

The lease is sixty seconds, longer than the thirty-second request timeout, so a handler that is
still alive is always cancelled, and its claim released, before its lease can lapse. Only a
process that died without releasing leaves a lease to expire, and the next request with the same
key takes that claim over. The replay window is twenty-four hours, after which the key is claimed
afresh; the slice 08 cleanup job deletes older rows.

A key is at most 255 printable ASCII characters. Anything else is refused as a validation error
before a claim is taken, so an oversized header can never become a row.
"""

import re
from enum import StrEnum

IDEMPOTENCY_KEY_HEADER = b"idempotency-key"
IDEMPOTENT_METHODS = frozenset({"POST", "PUT"})
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[\x21-\x7e]{1,255}$")
LEASE_SECONDS = 60
REPLAY_WINDOW_HOURS = 24
IDEMPOTENCY_KEY_STATE_ENUM_NAME = "request_idempotency_key_state"


class IdempotencyKeyState(StrEnum):
    """Where a claim is: its handler still running, or its response stored for replay."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
