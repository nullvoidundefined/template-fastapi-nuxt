"""Request and response models for `POST /v1/uploads`.

The request names a purpose and an extension and nothing else: `extra="forbid"` refuses a body
that tries to name its own key, and the validator refuses an extension outside the purpose's
allowlist, both as 400 `INPUT_VALIDATION_ERROR` before the route runs, so neither reaches R2.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.constants.uploads import MAX_EXTENSION_LENGTH, UPLOAD_CONTENT_TYPES, UploadPurpose


class PresignUploadRequest(BaseModel):
    """What the client wants to upload: its purpose and its file extension."""

    model_config = ConfigDict(extra="forbid")

    purpose: UploadPurpose
    extension: str = Field(min_length=1, max_length=MAX_EXTENSION_LENGTH)

    @model_validator(mode="after")
    def require_allowed_extension(self) -> Self:
        """Refuse an extension the purpose's allowlist does not name."""
        allowed_extensions = UPLOAD_CONTENT_TYPES[self.purpose]
        if self.extension not in allowed_extensions:
            allowed = ", ".join(sorted(allowed_extensions))
            raise ValueError(f"extension must be one of {allowed} for {self.purpose.value}")
        return self


class PresignedUploadData(BaseModel):
    """Everything the browser needs to PUT the file straight to R2."""

    upload_url: str
    key: str
    method: Literal["PUT"] = "PUT"
    content_type: str
    expires_in_seconds: int


class PresignedUploadResponse(BaseModel):
    """The success envelope for a presigned upload."""

    data: PresignedUploadData
