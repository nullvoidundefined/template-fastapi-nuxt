"""What an upload may be: each purpose's allowed extensions, the key shape, and the URL's life.

The extension decides the content type, and both come from this table rather than from the
client, so a purpose that accepts images can never be handed an HTML file to serve from the
bucket's origin (B-29).
"""

import re
from collections.abc import Mapping
from enum import StrEnum


class UploadPurpose(StrEnum):
    """What the uploaded file is for; each purpose has its own extension allowlist."""

    AVATAR = "avatar"


UPLOAD_CONTENT_TYPES: Mapping[UploadPurpose, Mapping[str, str]] = {
    UploadPurpose.AVATAR: {
        "jpeg": "image/jpeg",
        "jpg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    },
}
UPLOAD_URL_EXPIRY_SECONDS = 15 * 60
# `{user_id}/{uuid}.{extension}`, checked again on the generated key before anything is signed.
UPLOAD_KEY_PATTERN = re.compile(r"^[0-9a-f-]+/[0-9a-f-]+\.[a-z0-9]{1,5}$")
MAX_EXTENSION_LENGTH = 5
