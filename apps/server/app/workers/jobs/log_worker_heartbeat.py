"""The worker's heartbeat: one log line every five minutes, its only job until slice 04.

arq refuses to start a worker with no function or cron job registered, and the heartbeat also
lets the logs show a worker that is alive but idle.
"""

from typing import Any

import structlog

logger = structlog.get_logger()


async def log_worker_heartbeat(_ctx: dict[str, Any]) -> None:
    """Log one `worker_heartbeat` event."""
    logger.info("worker_heartbeat")
