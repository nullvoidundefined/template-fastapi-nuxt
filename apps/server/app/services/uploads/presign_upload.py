"""Generates an upload's object key and presigns a PUT for it (B-29).

The key is always `{user_id}/{uuid4}.{extension}`: the user's prefix scopes every object to its
owner, and the random name means two uploads never collide and no client can name, and so
overwrite, an existing object. The generated key is matched against the key pattern once more
before anything is signed, so a change that loosened the extension check upstream still could not
sign a path outside the user's prefix.
"""

import uuid
from dataclasses import dataclass

from app.clients.r2 import R2Client
from app.constants.uploads import (
    UPLOAD_CONTENT_TYPES,
    UPLOAD_KEY_PATTERN,
    UPLOAD_URL_EXPIRY_SECONDS,
    UploadPurpose,
)


@dataclass(slots=True, frozen=True)
class PresignedUpload:
    """A signed PUT: where to send the file, under which key, with which content type."""

    upload_url: str
    key: str
    content_type: str
    expires_in_seconds: int


async def presign_upload(
    storage_client: R2Client, user_id: uuid.UUID, purpose: UploadPurpose, extension: str
) -> PresignedUpload:
    """Build a fresh key under the user's prefix and presign a PUT for it."""
    content_type = UPLOAD_CONTENT_TYPES[purpose][extension]
    key = build_upload_key(user_id, extension)
    upload_url = await storage_client.presign_upload(key, content_type, UPLOAD_URL_EXPIRY_SECONDS)
    return PresignedUpload(upload_url, key, content_type, UPLOAD_URL_EXPIRY_SECONDS)


def build_upload_key(user_id: uuid.UUID, extension: str) -> str:
    """Return `{user_id}/{uuid4}.{extension}`, refusing anything that does not match the pattern."""
    key = f"{user_id}/{uuid.uuid4()}.{extension}"
    if UPLOAD_KEY_PATTERN.fullmatch(key) is None:
        raise ValueError("generated upload key does not match the key pattern")
    return key
