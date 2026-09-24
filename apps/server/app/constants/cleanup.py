"""How long the hourly cleanup job keeps each kind of row, and how many it deletes per statement.

An idempotency key is kept for its replay window, twenty-four hours, because after that it can
only ever be claimed afresh. A webhook ledger row is kept for thirty days, well past Stripe's
three-day redelivery window, so an operator investigating a delivery still finds it. Sessions have
no retention of their own: a session is deleted the moment its `expires_at` has passed.

Each DELETE removes at most one batch and commits, so a large backlog is worked through in many
short transactions rather than one that holds its row locks for as long as the whole backlog takes.
"""

from datetime import timedelta

from app.constants.idempotency import REPLAY_WINDOW_HOURS

CLEANUP_BATCH_SIZE = 1000
CLEANUP_CRON_MINUTE = 0
# arq's default is 300 seconds; a first run over a large backlog in the first table would spend
# it all and starve the tables after it, so the hourly job gets half its interval instead.
CLEANUP_JOB_TIMEOUT_SECONDS = 1800
IDEMPOTENCY_KEY_RETENTION = timedelta(hours=REPLAY_WINDOW_HOURS)
WEBHOOK_EVENT_RETENTION = timedelta(days=30)
