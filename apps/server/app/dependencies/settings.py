"""Provides the process settings to a route through the dependency chain.

Routes take this rather than calling `get_settings()` themselves, so a test can build an
application under one environment and have every route in it agree, and so nothing in a handler
reads the environment directly.
"""

from typing import Annotated

from fastapi import Depends

from app.core.settings import Settings, get_settings

RequestSettings = Annotated[Settings, Depends(get_settings)]
