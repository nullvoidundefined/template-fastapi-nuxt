"""Hands a route the application's integration clients, which `create_app()` builds once.

The clients live on `app.state` rather than in module globals, so each application a test builds
carries its own, and a test can replace one at the SDK boundary for a single application without
touching any other.
"""

from typing import Annotated, cast

from fastapi import Depends
from starlette.requests import Request

from app.clients.analytics import AnalyticsClient
from app.clients.r2 import R2Client
from app.constants.error_codes import ErrorCode
from app.errors import AppError

STORAGE_UNCONFIGURED_MESSAGE = "File uploads are not configured on this server"


class StorageUnconfiguredError(AppError):
    """The deployment has no R2 bucket, so nothing can be presigned."""

    def __init__(self) -> None:
        """Answer 503, since the failure is the server's configuration, not the request."""
        super().__init__(503, ErrorCode.UPLOADS_STORAGE_UNCONFIGURED, STORAGE_UNCONFIGURED_MESSAGE)


def get_analytics_client(request: Request) -> AnalyticsClient:
    """Return the application's analytics client, which is the no-op when PostHog is unkeyed."""
    return cast(AnalyticsClient, request.app.state.analytics_client)


def get_storage_client(request: Request) -> R2Client:
    """Return the application's R2 client, or answer 503 when none is configured."""
    storage_client = cast(R2Client | None, request.app.state.storage_client)
    if storage_client is None:
        raise StorageUnconfiguredError
    return storage_client


RequestAnalytics = Annotated[AnalyticsClient, Depends(get_analytics_client)]
RequestStorage = Annotated[R2Client, Depends(get_storage_client)]
