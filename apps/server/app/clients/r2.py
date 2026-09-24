"""Presigns Cloudflare R2 uploads through boto3's S3 client pointed at the account's endpoint.

The API never carries file bytes: it signs a PUT for one object key with a short expiry, and the
browser sends the file straight to R2. Signing is a local computation, but it runs in a worker
thread inside `with_client_telemetry` like every provider call, so it is logged and bounded, and
boto3's own connect and read timeouts are set for any call that does reach the network.

The key is never chosen here; `services/uploads/presign_upload.py` generates it. Without the four
R2 settings the factory logs one warning and returns None, and the upload route answers 503.
"""

import asyncio
from collections.abc import Mapping
from typing import Protocol, cast

import boto3
import structlog
from botocore.config import Config

from app.clients.telemetry import with_client_telemetry
from app.core.settings import Settings

R2_PROVIDER = "r2"
PRESIGN_UPLOAD_OPERATION = "presign_upload"
R2_TIMEOUT_SECONDS = 10.0
R2_REGION = "auto"
PUT_OBJECT_METHOD = "put_object"

logger = structlog.get_logger(__name__)


class S3Presigner(Protocol):
    """The one boto3 S3 client method this client calls."""

    def generate_presigned_url(
        self, *, ClientMethod: str, Params: Mapping[str, object], ExpiresIn: int  # noqa: N803
    ) -> str:
        """Return a URL authorizing the named operation until it expires."""


class R2Client:
    """Signs uploads into one bucket."""

    def __init__(self, s3_client: S3Presigner, bucket: str) -> None:
        """Hold the boto3 client and the bucket every key is signed into."""
        self.s3_client = s3_client
        self.bucket = bucket

    async def presign_upload(self, key: str, content_type: str, expires_in_seconds: int) -> str:
        """Return a URL that lets its holder PUT this one key with this content type."""

        async def presign(forwarded_headers: Mapping[str, str]) -> str:
            return await asyncio.to_thread(
                self.s3_client.generate_presigned_url,
                ClientMethod=PUT_OBJECT_METHOD,
                Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=expires_in_seconds,
            )

        return await with_client_telemetry(
            R2_PROVIDER, PRESIGN_UPLOAD_OPERATION, presign, R2_TIMEOUT_SECONDS
        )


def create_r2_client(settings: Settings) -> R2Client | None:
    """Build the client from settings, or return None with one warning when any value is missing."""
    account_id = settings.r2_account_id
    bucket = settings.r2_bucket
    access_key_id = settings.r2_access_key_id
    secret_access_key = settings.r2_secret_access_key
    if not (account_id and bucket and access_key_id and secret_access_key):
        logger.warning("storage_disabled", reason="the R2 settings are incomplete")
        return None
    s3_client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key_id.get_secret_value(),
        aws_secret_access_key=secret_access_key.get_secret_value(),
        region_name=R2_REGION,
        config=Config(
            signature_version="s3v4",
            connect_timeout=R2_TIMEOUT_SECONDS,
            read_timeout=R2_TIMEOUT_SECONDS,
        ),
    )
    return R2Client(cast(S3Presigner, s3_client), bucket)
