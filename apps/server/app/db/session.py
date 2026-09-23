"""The per-request connection and transaction, and the one place a failed connect is classified.

Every data-bearing route declares this as `Depends(get_connection, scope="function")`. Function
scope matters: under FastAPI's default request scope a dependency's exit code runs after the
response has been sent, so a commit that failed would follow a 201 the client already held. At
function scope the commit happens while the handler's exception handlers can still answer.

This is also the only place in the application where a connection is opened for a request, which
is why the database classification lives here. Registering `ConnectionError` and `socket.gaierror`
globally in `app/main.py` told a client the database was down for any route that raised a bare
socket error, database or not (IAN-169); a connect attempted here is unambiguous.
"""

from collections.abc import AsyncIterator

import structlog
from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.errors import DatabaseUnavailableError

# A refused connect arrives as `ConnectionRefusedError`, a wrong host as `socket.gaierror`, and a
# connect timeout as `TimeoutError`, all three of them `OSError` subclasses; a driver or pool
# failure arrives as a `SQLAlchemyError`. Nothing broader is caught, so a `CancelledError` from a
# disconnecting client still unwinds as cancellation rather than being reported as an outage.
CONNECT_FAILURE_TYPES = (OSError, SQLAlchemyError)

logger = structlog.get_logger(__name__)


async def get_connection(request: Request) -> AsyncIterator[AsyncConnection]:
    """Yield one connection in one transaction per request, committing only when the route returns.

    The transaction rolls back when the route raises, because the exception FastAPI throws back
    into this generator propagates out of the `connection.begin()` block. The connection is
    returned to the pool on every path, including cancellation, because `close()` runs in the
    `finally` as the generator unwinds.

    The connection is closed rather than re-entered as a context manager: `engine.connect()`
    already returns a started connection, and `async with connection` would start it a second time
    and raise before the route ever ran.
    """
    engine: AsyncEngine = request.app.state.engine
    try:
        connection = await engine.connect()
    except CONNECT_FAILURE_TYPES as err:
        logger.warning("request_database_connect_failed", error_type=type(err).__name__)
        raise DatabaseUnavailableError from err
    try:
        async with connection.begin():
            yield connection
    finally:
        await connection.close()
