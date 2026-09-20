"""B-5, B-9, and R-406 unit tests for the exception handlers register_exception_handlers installs.

Every failure, expected or not, answers in the `{ code, error }` envelope with a code from the
registry in `app/constants/error_codes.py`, and no response ever carries FastAPI's default
`{ detail }` body. The routing cases (an unknown path, a wrong method) run against the app the
existing `server_app` fixture builds, because they need no route of their own. Every other case
needs a route that raises, so it runs against an application the `build_server_app` factory builds
with the test-only router below mounted on it; `create_app()` never mounts that router, which one
test here asserts directly.

The 500 cases are built twice, once under `environment="production"` and once under
`environment="development"`, because the only difference the spec allows between them is whether
the exception's own message reaches the body. Neither may carry a traceback.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from app.constants.error_codes import ErrorCode
from app.errors import ConflictError, ForbiddenError, NotFoundError

UNKNOWN_PATH_MARKER = "zzmarkerpathzz"
UNKNOWN_PATH = f"/test-only/{UNKNOWN_PATH_MARKER}"

OPERATIONAL_ERROR_PATH = "/test-only/raise-operational-error"
OS_ERROR_PATH = "/test-only/raise-os-error"
UNEXPECTED_ERROR_PATH = "/test-only/raise-unexpected-error"
VALIDATED_BODY_PATH = "/test-only/validated-body"
APP_ERROR_PATH = "/test-only/raise-app-error"

ServerAppFactory = Callable[..., FastAPI]
ApiClientFactory = Callable[[FastAPI], AbstractAsyncContextManager[httpx.AsyncClient]]

FAILED_STATEMENT = "SELECT 1"
DATABASE_FAILURE_MESSAGE = "connection to server at 127.0.0.1 port 1 failed"
UNEXPECTED_ERROR_MESSAGE = "qqinternaldetailqq divide by cucumber"
REQUIRED_FIELD_NAME = "required_marker_field"

APP_ERROR_MESSAGE = "the thing you asked for is not available"
APP_ERROR_CASES = {
    "not_found": (404, ErrorCode.ROUTING_NOT_FOUND),
    "conflict": (409, ErrorCode.IDEMPOTENCY_KEY_REUSED),
    "forbidden": (403, ErrorCode.CSRF_HEADER_MISSING),
}


class ValidatedPayload(BaseModel):
    """Test-only request model, so FastAPI validates the body and raises RequestValidationError."""

    required_marker_field: str


def build_test_only_router() -> APIRouter:
    """Return a router whose routes raise each exception class a handler must map."""
    router = APIRouter()

    @router.get(OPERATIONAL_ERROR_PATH)
    async def raise_operational_error() -> dict[str, str]:
        raise OperationalError(FAILED_STATEMENT, None, OSError(DATABASE_FAILURE_MESSAGE))

    @router.get(OS_ERROR_PATH)
    async def raise_os_error() -> dict[str, str]:
        raise OSError(DATABASE_FAILURE_MESSAGE)

    @router.get(UNEXPECTED_ERROR_PATH)
    async def raise_unexpected_error() -> dict[str, str]:
        raise RuntimeError(UNEXPECTED_ERROR_MESSAGE)

    @router.post(VALIDATED_BODY_PATH)
    async def read_validated_body(payload: ValidatedPayload) -> dict[str, int]:
        return {"field_length": len(payload.required_marker_field)}

    @router.get(f"{APP_ERROR_PATH}/{{error_name}}")
    async def raise_app_error(error_name: str) -> dict[str, str]:
        _status_code, error_code = APP_ERROR_CASES[error_name]
        if error_name == "not_found":
            raise NotFoundError(code=error_code, message=APP_ERROR_MESSAGE)
        if error_name == "conflict":
            raise ConflictError(code=error_code, message=APP_ERROR_MESSAGE)
        raise ForbiddenError(code=error_code, message=APP_ERROR_MESSAGE)

    return router


def assert_error_envelope(
    response: httpx.Response, expected_status: int, expected_code: ErrorCode
) -> dict[str, object]:
    """Assert the response is the { code, error } envelope with one status and one code."""
    assert response.status_code == expected_status, response.text
    response_body = response.json()
    assert "detail" not in response_body, response_body
    assert response_body["code"] == expected_code, response_body
    assert isinstance(response_body["error"], str), response_body
    assert response_body["error"].strip(), response_body
    return response_body


async def test_b5_unknown_path_answers_404_routing_not_found_without_echoing_the_path(
    api_client: httpx.AsyncClient,
) -> None:
    """B-5: an unknown path answers 404 ROUTING_NOT_FOUND, and the body never repeats the path."""
    response = await api_client.get(UNKNOWN_PATH)

    response_body = assert_error_envelope(response, 404, ErrorCode.ROUTING_NOT_FOUND)
    assert set(response_body) == {"code", "error"}, response_body
    assert UNKNOWN_PATH_MARKER not in response.text, response.text


async def test_b5_wrong_method_on_a_real_route_answers_405_routing_method_not_allowed(
    api_client: httpx.AsyncClient,
) -> None:
    """B-5: POST to the GET-only /health answers 405 ROUTING_METHOD_NOT_ALLOWED, not { detail }."""
    response = await api_client.post("/health")

    response_body = assert_error_envelope(response, 405, ErrorCode.ROUTING_METHOD_NOT_ALLOWED)
    assert set(response_body) == {"code", "error"}, response_body


async def test_create_app_does_not_mount_the_test_only_router(
    api_client: httpx.AsyncClient,
) -> None:
    """The test-only routes exist only on the factory-built app: create_app() answers 404."""
    response = await api_client.get(UNEXPECTED_ERROR_PATH)

    assert_error_envelope(response, 404, ErrorCode.ROUTING_NOT_FOUND)


async def test_b9_operational_error_answers_503_server_database_unavailable(
    build_server_app: ServerAppFactory, build_api_client: ApiClientFactory
) -> None:
    """B-9: a route raising SQLAlchemy's OperationalError answers 503, not 500."""
    application = build_server_app(test_only_router=build_test_only_router())

    async with build_api_client(application) as client:
        response = await client.get(OPERATIONAL_ERROR_PATH)

    assert_error_envelope(response, 503, ErrorCode.SERVER_DATABASE_UNAVAILABLE)


async def test_b9_os_error_from_a_failed_connect_answers_503_server_database_unavailable(
    build_server_app: ServerAppFactory, build_api_client: ApiClientFactory
) -> None:
    """B-9: a bare OSError, the shape a failed asyncpg connect takes, answers 503 and not 500.

    Slice 01's readiness route catches `(OSError, SQLAlchemyError)`, which is the evidence that a
    real connect failure can arrive as an OSError the SQLAlchemy hierarchy never wraps.
    """
    application = build_server_app(test_only_router=build_test_only_router())

    async with build_api_client(application) as client:
        response = await client.get(OS_ERROR_PATH)

    assert_error_envelope(response, 503, ErrorCode.SERVER_DATABASE_UNAVAILABLE)


async def test_b9_unexpected_error_in_production_answers_500_without_the_exception_message(
    build_server_app: ServerAppFactory, build_api_client: ApiClientFactory
) -> None:
    """B-9: under production the 500 body carries neither the exception message nor a traceback."""
    application = build_server_app(
        test_only_router=build_test_only_router(), environment="production"
    )

    async with build_api_client(application) as client:
        response = await client.get(UNEXPECTED_ERROR_PATH)

    assert_error_envelope(response, 500, ErrorCode.SERVER_INTERNAL_ERROR)
    assert UNEXPECTED_ERROR_MESSAGE not in response.text, response.text
    assert "Traceback" not in response.text, response.text
    assert "raise_unexpected_error" not in response.text, response.text


async def test_b9_unexpected_error_in_development_answers_500_carrying_the_exception_message(
    build_server_app: ServerAppFactory, build_api_client: ApiClientFactory
) -> None:
    """B-9: outside production the 500 body carries the exception's message, still no traceback."""
    application = build_server_app(
        test_only_router=build_test_only_router(), environment="development"
    )

    async with build_api_client(application) as client:
        response = await client.get(UNEXPECTED_ERROR_PATH)

    response_body = assert_error_envelope(response, 500, ErrorCode.SERVER_INTERNAL_ERROR)
    assert UNEXPECTED_ERROR_MESSAGE in str(response_body["error"]), response_body
    assert "Traceback" not in response.text, response.text


@pytest.mark.parametrize(
    "invalid_payload",
    [{}, {"required_marker_field": 12}, {"unexpected_field": "value"}],
    ids=["missing", "wrong-type", "unknown-field-only"],
)
async def test_r406_invalid_body_answers_400_input_validation_error_with_the_field_errors(
    build_server_app: ServerAppFactory,
    build_api_client: ApiClientFactory,
    invalid_payload: dict[str, object],
) -> None:
    """RequestValidationError becomes 400 INPUT_VALIDATION_ERROR naming the offending field."""
    application = build_server_app(test_only_router=build_test_only_router())

    async with build_api_client(application) as client:
        response = await client.post(VALIDATED_BODY_PATH, json=invalid_payload)

    assert_error_envelope(response, 400, ErrorCode.INPUT_VALIDATION_ERROR)
    assert REQUIRED_FIELD_NAME in response.text, response.text


async def test_r406_malformed_json_body_answers_400_input_validation_error(
    build_server_app: ServerAppFactory, build_api_client: ApiClientFactory
) -> None:
    """R-406: a body that is not JSON at all answers the envelope, never a 500 or { detail }."""
    application = build_server_app(test_only_router=build_test_only_router())

    async with build_api_client(application) as client:
        response = await client.post(
            VALIDATED_BODY_PATH,
            content=b"{not json at all",
            headers={"content-type": "application/json"},
        )

    assert_error_envelope(response, 400, ErrorCode.INPUT_VALIDATION_ERROR)


@pytest.mark.parametrize("error_name", sorted(APP_ERROR_CASES))
async def test_app_error_subclasses_answer_their_own_status_and_code_not_500(
    build_server_app: ServerAppFactory, build_api_client: ApiClientFactory, error_name: str
) -> None:
    """An AppError subclass raised in a route answers its own status, code, and message."""
    expected_status, expected_code = APP_ERROR_CASES[error_name]
    application = build_server_app(test_only_router=build_test_only_router())

    async with build_api_client(application) as client:
        response = await client.get(f"{APP_ERROR_PATH}/{error_name}")

    response_body = assert_error_envelope(response, expected_status, expected_code)
    assert response_body["error"] == APP_ERROR_MESSAGE, response_body
