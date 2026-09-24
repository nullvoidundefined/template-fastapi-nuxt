"""Provides the application's database engine to a route that runs its own transactions.

Almost every route takes `RequestConnection`, one transaction that commits when the route returns.
The Stripe webhook cannot: its ledger claim has to commit before the handler runs, so a concurrent
redelivery sees it, and a failure has to be recorded after the handler's own writes rolled back.
It takes the engine instead and opens each short transaction itself.
"""

from typing import Annotated, cast

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.requests import Request


def get_database_engine(request: Request) -> AsyncEngine:
    """Return the engine the lifespan stored on the application."""
    return cast("AsyncEngine", request.app.state.engine)


RequestEngine = Annotated[AsyncEngine, Depends(get_database_engine)]
