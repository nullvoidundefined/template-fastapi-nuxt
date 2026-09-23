"""Specify password comparison structure, worker execution, and session token properties."""

import ast
import hashlib
import inspect
import re
import textwrap
import threading
from collections.abc import Callable

import pytest

DUMMY_PASSWORD = "-".join(("timing", "equalizer"))
CANDIDATE_PASSWORD = " ".join(("correct", "horse", "battery", "staple"))


def encode_hash(value: str | bytes) -> bytes:
    """Encode a textual bcrypt hash without changing an already encoded hash."""
    return value.encode() if isinstance(value, str) else value


async def test_password_hashes_are_salted_cost_twelve_and_verify() -> None:
    """The stored hash carries cost twelve and verifies only the correct password."""
    from app.core.security import hash_password, verify_password  # noqa: PLC0415

    first_hash = await hash_password(CANDIDATE_PASSWORD)
    second_hash = await hash_password(CANDIDATE_PASSWORD)
    assert first_hash != second_hash
    for password_hash in (first_hash, second_hash):
        assert int(encode_hash(password_hash).split(b"$")[2]) == 12
        assert await verify_password(CANDIDATE_PASSWORD, password_hash) is True
        assert await verify_password("incorrect candidate", password_hash) is False


async def test_comparison_hash_resolves_none_and_preserves_a_real_hash() -> None:
    """Missing users select the module dummy while real users retain their own hash."""
    from app.core.security import (  # noqa: PLC0415
        _DUMMY_PASSWORD_HASH,
        hash_password,
        resolve_comparison_hash,
    )

    real_hash = await hash_password(CANDIDATE_PASSWORD)
    assert encode_hash(resolve_comparison_hash(None)) == encode_hash(_DUMMY_PASSWORD_HASH)
    assert encode_hash(resolve_comparison_hash(real_hash)) == encode_hash(real_hash)


def test_dummy_hash_verifies_the_known_dummy_password() -> None:
    """The dummy is a real cost-twelve bcrypt hash rather than a shaped placeholder."""
    import bcrypt  # noqa: PLC0415
    from app.core.security import resolve_comparison_hash  # noqa: PLC0415

    dummy_hash = encode_hash(resolve_comparison_hash(None))
    assert re.fullmatch(rb"\$2[aby]\$12\$[./A-Za-z0-9]{53}", dummy_hash)
    assert bcrypt.checkpw(DUMMY_PASSWORD.encode(), dummy_hash) is True


async def test_missing_user_rejects_even_the_dummy_password() -> None:
    """A successful dummy comparison never authenticates a nonexistent user."""
    from app.core.security import verify_password  # noqa: PLC0415

    assert await verify_password(DUMMY_PASSWORD, None) is False


def test_verification_has_one_unconditional_comparison_after_resolving_hash() -> None:
    """Reject early returns and branches that would skip comparison for unknown users.

    The three dummy-value tests alone do not reject an unused resolver paired with a
    short-circuit verifier. This structural contract connects them to the public verifier.
    """
    from app.core.security import verify_password  # noqa: PLC0415

    function = ast.parse(textwrap.dedent(inspect.getsource(verify_password))).body[0]
    assert isinstance(function, ast.AsyncFunctionDef)
    assert not any(isinstance(node, (ast.If, ast.IfExp, ast.Match)) for node in ast.walk(function))
    returns = [node for node in ast.walk(function) if isinstance(node, ast.Return)]
    assert len(returns) == 1
    assert function.body[-1] is returns[0]
    resolutions = [
        node
        for node in function.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "resolve_comparison_hash"
    ]
    assert len(resolutions) == 1
    target = resolutions[0].targets[0]
    assert isinstance(target, ast.Name)
    comparisons = [node for node in ast.walk(function) if isinstance(node, ast.Await)]
    assert len(comparisons) == 1
    assert isinstance(comparisons[0].value, ast.Call)
    assert any(
        isinstance(statement, (ast.Assign, ast.AnnAssign, ast.Expr))
        and statement.value is comparisons[0]
        for statement in function.body
    )
    assert any(
        isinstance(node, ast.Name) and node.id == target.id
        for argument in comparisons[0].value.args
        for node in ast.walk(argument)
    )
    assert resolutions[0].lineno < comparisons[0].lineno <= returns[0].lineno


@pytest.mark.parametrize("operation", ["hash", "verify", "missing"])
async def test_bcrypt_executes_outside_the_event_loop(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Real bcrypt operations refuse execution on the event-loop thread.

    The wrappers still compute real hashes and comparisons. There are no call-count or
    duration assertions; synchronous bcrypt fails at the point it blocks the loop.
    """
    import bcrypt  # noqa: PLC0415
    from app.core.security import hash_password, verify_password  # noqa: PLC0415

    stored_hash = await hash_password(CANDIDATE_PASSWORD)
    event_loop_thread = threading.get_ident()

    def guard_worker(function: Callable[..., bytes | bool]) -> Callable[..., bytes | bool]:
        """Wrap a real bcrypt operation with its execution-context invariant."""

        def execute_in_worker(*arguments: bytes) -> bytes | bool:
            """Compute the real result only when execution is outside the event loop."""
            assert threading.get_ident() != event_loop_thread
            return function(*arguments)

        return execute_in_worker

    monkeypatch.setattr(bcrypt, "hashpw", guard_worker(bcrypt.hashpw))
    monkeypatch.setattr(bcrypt, "checkpw", guard_worker(bcrypt.checkpw))
    if operation == "hash":
        result = await hash_password(CANDIDATE_PASSWORD)
        assert await verify_password(CANDIDATE_PASSWORD, result) is True
    else:
        expected = operation == "verify"
        assert (
            await verify_password(CANDIDATE_PASSWORD, stored_hash if expected else None) is expected
        )


def test_session_tokens_have_urlsafe_32_byte_shape_and_matching_sha256() -> None:
    """Tokens contain 43 URL-safe characters and store the SHA-256 of the raw value."""
    from app.core.security import generate_session_token  # noqa: PLC0415

    tokens = [generate_session_token() for _ in range(2)]
    assert tokens[0][0] != tokens[1][0]
    for raw_token, token_hash in tokens:
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", raw_token)
        assert token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
        assert token_hash != raw_token
