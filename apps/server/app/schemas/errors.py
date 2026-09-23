"""The failure half of the response contract: every error answers `{ code, error }`.

Declaring it as a Pydantic model rather than building a bare dict is what puts the shape into
`openapi.yaml`, and from there into `@repo/api-types`, so the frontend's error handling is typed
from the same source as the success bodies rather than known only by convention.
"""

from pydantic import BaseModel, Field

from app.constants.error_codes import ErrorCode


class FieldError(BaseModel):
    """One field of a request body that failed validation, and why."""

    field: str = Field(description="The offending field, as a dotted path without the body prefix.")
    message: str = Field(description="Why this field was rejected.")


class ErrorResponse(BaseModel):
    """One failed request: a registry code the client switches on and a human-readable message.

    `field_errors` is populated only for `INPUT_VALIDATION_ERROR` and omitted from the body
    entirely otherwise, so every other failure keeps the two-key shape clients already handle. It
    exists because a form has to show a message beside the input it belongs to, and the prose
    `error` string is documented as never parsed; reading the field out of it would make a
    human-readable sentence into an interface.
    """

    code: ErrorCode = Field(description="Machine-readable code from the error registry.")
    error: str = Field(description="Human-readable message; never parsed by clients.")
    field_errors: list[FieldError] | None = Field(
        default=None, description="Per-field validation failures, present only for a 400."
    )
