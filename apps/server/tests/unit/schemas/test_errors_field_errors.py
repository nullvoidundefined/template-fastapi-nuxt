"""The additive half of the error envelope: a structured field-error list beside the prose.

`ErrorResponse.error` is documented as never parsed by clients, and `summarize_field_errors`
flattens every field error into that one string. A form cannot put a message beside the input it
belongs to from a sentence, so B-38 needs the same information in a shape a client may read:
`field_errors`, a list of `{ field, message }`, present only when a failure names fields.

Present only, not null: every existing handler and middleware builds the same envelope through
`build_error_response` and `send_error_envelope`, and several tests assert that a failed request
carries exactly `code` and `error`. The addition therefore has to be omitted from the body when
there is nothing to say, which is what the first test pins.

The OpenAPI test is here because this is a contract change: the field has to reach the exported
document, and from there `@repo/api-types`, or the frontend in PR 4 is back to reading prose.
"""

import importlib
import json
from collections.abc import Iterator
from typing import Any

import pytest

from app.constants.error_codes import ErrorCode

ERROR_MESSAGE = "The request body failed validation: email: value is not a valid email address"
FIELD_MESSAGE = "value is not a valid email address"
EXPORT_DATABASE_URL = "postgresql+asyncpg://127.0.0.1:1/none"


def clear_settings_cache() -> None:
    """Drop the cached Settings so the next get_settings() reads the patched environment."""
    from app.core.settings import get_settings  # noqa: PLC0415

    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def export_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Patch DATABASE_URL and ENVIRONMENT so the document builds without a real database."""
    monkeypatch.setenv("DATABASE_URL", EXPORT_DATABASE_URL)
    monkeypatch.setenv("ENVIRONMENT", "test")
    clear_settings_cache()
    yield
    clear_settings_cache()


def build_current_document() -> dict[str, Any]:
    """Return the OpenAPI document the export builds for the current application."""
    document: dict[str, Any] = importlib.import_module(
        "app.export_openapi"
    ).build_openapi_document()
    return document


def test_the_envelope_omits_the_field_error_list_unless_a_failure_names_fields() -> None:
    """A failure that names no field answers exactly `{ code, error }`, as it always has."""
    from app.errors import build_error_response  # noqa: PLC0415
    from app.schemas.errors import FieldError  # noqa: PLC0415

    plain = json.loads(
        build_error_response(404, ErrorCode.ROUTING_NOT_FOUND, "The resource was not found").body
    )
    annotated = json.loads(
        build_error_response(
            400,
            ErrorCode.INPUT_VALIDATION_ERROR,
            ERROR_MESSAGE,
            field_errors=[FieldError(field="email", message=FIELD_MESSAGE)],
        ).body
    )

    assert set(plain) == {"code", "error"}
    assert set(annotated) == {"code", "error", "field_errors"}
    assert annotated["error"] == ERROR_MESSAGE
    assert annotated["field_errors"] == [{"field": "email", "message": FIELD_MESSAGE}]


def test_a_field_error_carries_exactly_the_field_name_and_its_message() -> None:
    """One entry is `{ field, message }` and nothing else, so a client can bind it to an input."""
    from app.schemas.errors import FieldError  # noqa: PLC0415

    entry = FieldError(field="email", message=FIELD_MESSAGE)

    assert set(FieldError.model_fields) == {"field", "message"}
    assert entry.model_dump(mode="json") == {"field": "email", "message": FIELD_MESSAGE}


def test_the_exported_document_declares_the_field_error_list_as_optional() -> None:
    """The contract reaches openapi.yaml: a FieldError schema, and an optional list of them."""
    component_schemas = build_current_document()["components"]["schemas"]

    assert "FieldError" in component_schemas
    assert set(component_schemas["FieldError"]["properties"]) == {"field", "message"}
    assert sorted(component_schemas["FieldError"]["required"]) == ["field", "message"]
    error_response = component_schemas["ErrorResponse"]
    assert "field_errors" in error_response["properties"]
    assert "field_errors" not in error_response.get("required", [])


def test_the_exported_document_lists_the_duplicate_registration_code() -> None:
    """The new code is part of the published enum, so a client can switch on it."""
    component_schemas = build_current_document()["components"]["schemas"]

    assert "AUTH_EMAIL_ALREADY_REGISTERED" in component_schemas["ErrorCode"]["enum"]
