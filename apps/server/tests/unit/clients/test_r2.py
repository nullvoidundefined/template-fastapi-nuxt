"""B-29 unit tests for the Cloudflare R2 client in app/clients/r2.py.

Presigning is a local signature computation, so these tests run a real boto3 client against
placeholder credentials and read the URL it produced: the host is the account's R2 endpoint, the
path is the bucket and the key, the method signed is PUT with the content type, and the expiry is
the one requested. No network is involved. Without the four R2 settings the factory returns
nothing and logs one warning, so an unconfigured deployment refuses uploads rather than signing
URLs against a bucket that does not exist.
"""

from urllib.parse import parse_qs, urlsplit

import structlog

ACCOUNT_ID = "0123456789abcdef0123456789abcdef"
BUCKET = "template-uploads"
OBJECT_KEY = "5f0b1f9c-3a4e-4c1d-9a51-0d2f6c7e8a10/1c7e7f52-6a1e-4b1a-8f41-6a3c0f4f2b9e.png"
FIFTEEN_MINUTES = 900
# Placeholders built from parts, never a credential-shaped literal (R-108).
ACCESS_KEY_ID = "".join(("placeholder", "access", "id"))
SECRET_ACCESS_KEY = "".join(("placeholder", "secret", "value"))


def build_settings(**overrides: object) -> object:
    """Build Settings with a database URL, so the constructor has what it requires."""
    from app.core.settings import Settings  # noqa: PLC0415

    return Settings(database_url="postgresql+asyncpg://127.0.0.1:1/none", **overrides)


def build_configured_settings() -> object:
    """Return settings naming an account, a bucket, and a key pair."""
    return build_settings(
        r2_account_id=ACCOUNT_ID,
        r2_bucket=BUCKET,
        r2_access_key_id=ACCESS_KEY_ID,
        r2_secret_access_key=SECRET_ACCESS_KEY,
    )


async def test_b29_a_presigned_put_targets_the_bucket_key_and_expires_in_fifteen_minutes() -> None:
    """The URL names the R2 endpoint, the bucket and key, and carries the requested expiry."""
    from app.clients.r2 import create_r2_client  # noqa: PLC0415

    storage_client = create_r2_client(build_configured_settings())
    assert storage_client is not None

    upload_url = await storage_client.presign_upload(OBJECT_KEY, "image/png", FIFTEEN_MINUTES)

    parts = urlsplit(upload_url)
    query = parse_qs(parts.query)
    assert parts.scheme == "https"
    assert parts.hostname == f"{ACCOUNT_ID}.r2.cloudflarestorage.com"
    assert parts.path == f"/{BUCKET}/{OBJECT_KEY}"
    assert query["X-Amz-Expires"] == [str(FIFTEEN_MINUTES)]
    assert "content-type" in query["X-Amz-SignedHeaders"][0]
    assert SECRET_ACCESS_KEY not in upload_url


async def test_b23_presigning_is_logged_as_an_r2_client_call() -> None:
    """The presign goes through the telemetry wrapper, so it logs provider and outcome."""
    from app.clients.r2 import create_r2_client  # noqa: PLC0415

    storage_client = create_r2_client(build_configured_settings())
    assert storage_client is not None

    with structlog.testing.capture_logs() as captured_events:
        await storage_client.presign_upload(OBJECT_KEY, "image/png", FIFTEEN_MINUTES)

    [call_event] = [event for event in captured_events if event.get("provider") == "r2"]
    assert call_event["operation"] == "presign_upload"
    assert call_event["outcome"] == "success"


def test_b29_without_the_r2_settings_there_is_no_client_and_one_warning() -> None:
    """A missing account, bucket, or key pair yields no client, and the operator is told once."""
    from app.clients.r2 import create_r2_client  # noqa: PLC0415

    with structlog.testing.capture_logs() as captured_events:
        storage_client = create_r2_client(build_settings(r2_bucket=BUCKET))

    assert storage_client is None
    assert [event["event"] for event in captured_events] == ["storage_disabled"]
