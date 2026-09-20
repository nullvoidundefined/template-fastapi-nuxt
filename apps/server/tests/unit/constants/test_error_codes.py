"""Unit tests for the error-code registry in app/constants/error_codes.py.

Clients switch on the code, never on the message, so a code is part of the API contract: it is a
string when it is serialized, its value equals its member name so the registry cannot drift from
what the wire carries, and every code the envelope raises in this slice, plus the
`SERVER_RATE_LIMIT_UNAVAILABLE` the rate limiter raises in a later PR, is registered rather than
written as a literal at a call site.
"""

import json
from enum import StrEnum

import pytest

from app.constants.error_codes import ErrorCode

REQUIRED_CODE_NAMES = [
    "INPUT_PAYLOAD_TOO_LARGE",
    "INPUT_VALIDATION_ERROR",
    "ROUTING_METHOD_NOT_ALLOWED",
    "ROUTING_NOT_FOUND",
    "SERVER_DATABASE_UNAVAILABLE",
    "SERVER_INTERNAL_ERROR",
    "SERVER_RATE_LIMIT_UNAVAILABLE",
]


@pytest.mark.parametrize("code_name", REQUIRED_CODE_NAMES)
def test_registry_holds_every_code_the_error_envelope_answers_with(code_name: str) -> None:
    """Each code the handlers and the middleware answer with is a member of the registry."""
    registered_names = {member.name for member in ErrorCode}

    assert code_name in registered_names, sorted(registered_names)


def test_every_registered_code_value_equals_its_member_name() -> None:
    """A member's wire value is its own name, so the registry cannot drift from the response."""
    mismatched_members = {
        member.name: member.value for member in ErrorCode if member.value != member.name
    }

    assert mismatched_members == {}


def test_a_registered_code_serializes_to_json_as_its_bare_string() -> None:
    """ErrorCode is a StrEnum, so json.dumps writes the code and never an enum repr."""
    serialized_body = json.dumps({"code": ErrorCode.SERVER_INTERNAL_ERROR})

    assert issubclass(ErrorCode, StrEnum)
    assert serialized_body == '{"code": "SERVER_INTERNAL_ERROR"}'
