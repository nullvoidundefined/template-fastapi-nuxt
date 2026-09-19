"""Response models for the liveness and readiness probes, so the OpenAPI document types both."""

from typing import Literal

from pydantic import BaseModel


class HealthLiveness(BaseModel):
    """Body of `GET /health`: the process is up."""

    status: Literal["ok"]


class HealthReadiness(BaseModel):
    """Body of `GET /health/ready`: whether Postgres answered within the deadline."""

    status: Literal["ok", "degraded"]
    db: Literal["connected", "disconnected"]
