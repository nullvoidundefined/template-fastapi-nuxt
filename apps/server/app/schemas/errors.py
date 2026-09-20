"""The failure half of the response contract: every error answers `{ code, error }`.

Declaring it as a Pydantic model rather than building a bare dict is what puts the shape into
`openapi.yaml`, and from there into `@repo/api-types`, so the frontend's error handling is typed
from the same source as the success bodies rather than known only by convention.
"""

from pydantic import BaseModel, Field

from app.constants.error_codes import ErrorCode


class ErrorResponse(BaseModel):
    """One failed request: a registry code the client switches on and a human-readable message."""

    code: ErrorCode = Field(description="Machine-readable code from the error registry.")
    error: str = Field(description="Human-readable message; never parsed by clients.")
