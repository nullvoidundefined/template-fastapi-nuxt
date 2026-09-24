"""B-29: `POST /v1/uploads` presigns an R2 PUT for a key the server generates, and nothing else.

The key is `{user_id}/{uuid}.{extension}`, the extension comes from the purpose's allowlist, and
the URL expires in fifteen minutes. A body that names its own key, or an extension the purpose
does not allow, is refused with 400 before anything reaches R2, which the recording boto3 client
proves by staying empty. Every assertion is made on what the application assembled by
`create_app()` answered.
"""

import re

import pytest

UPLOADS_PATH = "/v1/uploads"
FIFTEEN_MINUTES = 900
UUID_PATTERN = "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"


@pytest.mark.integration
async def test_b29_a_valid_request_presigns_a_server_generated_key(
    uploads_client, uploads_harness
) -> None:
    """The answer carries the URL, the key under the user's prefix, the type, and the expiry."""
    response = await uploads_client.post(
        UPLOADS_PATH, json={"purpose": "avatar", "extension": "png"}
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    key_pattern = rf"^{uploads_harness.user_id}/{UUID_PATTERN}\.png$"
    assert re.fullmatch(key_pattern, data["key"]), data["key"]
    assert data["upload_url"] == "https://r2.example.test/presigned-put"
    assert data["method"] == "PUT"
    assert data["content_type"] == "image/png"
    assert data["expires_in_seconds"] == FIFTEEN_MINUTES
    assert uploads_harness.s3_client.presign_calls == [
        {
            "ClientMethod": "put_object",
            "Params": {
                "Bucket": "template-uploads-test",
                "Key": data["key"],
                "ContentType": "image/png",
            },
            "ExpiresIn": FIFTEEN_MINUTES,
        }
    ]


@pytest.mark.integration
async def test_b29_each_presign_gets_a_fresh_key(uploads_client) -> None:
    """Two requests never share a key, so one upload cannot overwrite another."""
    body = {"purpose": "avatar", "extension": "webp"}

    first = await uploads_client.post(UPLOADS_PATH, json=body)
    second = await uploads_client.post(UPLOADS_PATH, json=body)

    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["key"] != second.json()["data"]["key"]


@pytest.mark.integration
async def test_b29_a_client_supplied_key_is_refused_before_any_r2_call(
    uploads_client, uploads_harness
) -> None:
    """A body naming its own key answers 400 and presigns nothing."""
    response = await uploads_client.post(
        UPLOADS_PATH,
        json={"purpose": "avatar", "extension": "png", "key": "someone-else/avatar.png"},
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INPUT_VALIDATION_ERROR"
    assert uploads_harness.s3_client.presign_calls == []


@pytest.mark.integration
@pytest.mark.parametrize("extension", ["exe", "svg", "html", "PNG", "png/../x", "p.ng", ""])
async def test_b29_a_disallowed_extension_is_refused_before_any_r2_call(
    uploads_client, uploads_harness, extension: str
) -> None:
    """An extension outside the purpose's allowlist answers 400 and presigns nothing."""
    response = await uploads_client.post(
        UPLOADS_PATH, json={"purpose": "avatar", "extension": extension}
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INPUT_VALIDATION_ERROR"
    assert uploads_harness.s3_client.presign_calls == []


@pytest.mark.integration
@pytest.mark.parametrize(
    "body",
    [
        {"purpose": "'; DROP TABLE users; --", "extension": "png"},
        {"purpose": "avatar"},
        {"purpose": "avatar", "extension": "x" * 10_000},
    ],
)
async def test_r406_malformed_bodies_are_refused_before_any_r2_call(
    uploads_client, uploads_harness, body: dict[str, str]
) -> None:
    """An unknown purpose, a missing extension, or an oversized one answers 400."""
    response = await uploads_client.post(UPLOADS_PATH, json=body)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INPUT_VALIDATION_ERROR"
    assert uploads_harness.s3_client.presign_calls == []


@pytest.mark.integration
async def test_b29_an_anonymous_request_is_refused_before_any_r2_call(
    uploads_harness,
) -> None:
    """Without a session the route answers 401 and presigns nothing."""
    import httpx  # noqa: PLC0415

    application = uploads_harness.application
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with (
        application.router.lifespan_context(application),
        httpx.AsyncClient(
            transport=transport,
            base_url="https://testserver",
            headers={"X-Requested-With": "XMLHttpRequest"},
        ) as anonymous_client,
    ):
        response = await anonymous_client.post(
            UPLOADS_PATH, json={"purpose": "avatar", "extension": "png"}
        )

    assert response.status_code == 401, response.text
    assert response.json()["code"] == "AUTH_REQUIRED"
    assert uploads_harness.s3_client.presign_calls == []


@pytest.mark.integration
async def test_b29_without_r2_configured_the_route_answers_503(
    uploads_client, uploads_harness
) -> None:
    """An unconfigured deployment refuses the upload rather than signing for no bucket."""
    uploads_harness.application.state.storage_client = None

    response = await uploads_client.post(
        UPLOADS_PATH, json={"purpose": "avatar", "extension": "png"}
    )

    assert response.status_code == 503, response.text
    assert response.json()["code"] == "UPLOADS_STORAGE_UNCONFIGURED"
