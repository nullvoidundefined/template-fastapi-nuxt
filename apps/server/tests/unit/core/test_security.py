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


def parse_async_function(function: Callable[..., object]) -> ast.AsyncFunctionDef:
    """Return the parsed definition of an async function, dedented so its source stands alone."""
    parsed = ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]
    assert isinstance(parsed, ast.AsyncFunctionDef)
    return parsed


def find_single_awaited_call(function: ast.AsyncFunctionDef) -> ast.Call:
    """Return the one call the function awaits, asserting that there is exactly one."""
    awaited = [node for node in ast.walk(function) if isinstance(node, ast.Await)]
    assert len(awaited) == 1
    assert isinstance(awaited[0].value, ast.Call)
    return awaited[0].value


def find_comparison_hash_variable(function: ast.AsyncFunctionDef) -> str:
    """Return the name the function binds the output of `resolve_comparison_hash` to."""
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
    return target.id


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


def test_verification_hands_bcrypt_checkpw_the_candidate_and_the_resolved_hash_directly() -> None:
    """Reject a worker callable that wraps bcrypt, where a skipped comparison can still hide.

    The structural test above is satisfied by this implementation, and so is every value
    assertion in this module and the thread test below it:

        matched = await asyncio.to_thread(
            lambda h: stored_hash is not None and bcrypt.checkpw(candidate.encode(), h),
            comparison_hash,
        )

    It has one return, one await, no conditional statement, and it names the resolved hash in the
    arguments of the awaited call, yet it never reaches bcrypt at all for an address no user has.
    An unknown email would then cost a thread hop instead of a quarter second of hashing, which is
    the timing difference B-11 exists to remove and an oracle for which addresses have accounts.

    What closes the hole is that the work handed to the worker thread is `bcrypt.checkpw` itself,
    referenced as an attribute rather than wrapped in a callable that may decline to call it, with
    the candidate and the resolved hash passed to it directly as its arguments. That is asserted
    here on the source, not on a recorded call: a mock-call assertion would be the anti-pattern
    R-401 bans, and is why this property is pinned structurally in the first place.
    """
    from app.core.security import verify_password  # noqa: PLC0415

    function = parse_async_function(verify_password)
    worker_call = find_single_awaited_call(function)

    assert isinstance(worker_call.func, ast.Attribute)
    assert isinstance(worker_call.func.value, ast.Name)
    assert (worker_call.func.value.id, worker_call.func.attr) == ("asyncio", "to_thread")
    assert not worker_call.keywords
    assert worker_call.args, ast.unparse(worker_call)

    worker = worker_call.args[0]
    assert isinstance(
        worker, ast.Attribute
    ), f"the worker must be bcrypt.checkpw itself, not {ast.unparse(worker)}"
    assert isinstance(worker.value, ast.Name)
    assert (worker.value.id, worker.attr) == ("bcrypt", "checkpw")
    assert len(worker_call.args) == 3, ast.unparse(worker_call)

    encoded_candidate, comparison_argument = worker_call.args[1:]
    candidate_parameter = function.args.args[0].arg
    assert isinstance(encoded_candidate, ast.Call), ast.unparse(encoded_candidate)
    assert isinstance(encoded_candidate.func, ast.Attribute)
    assert encoded_candidate.func.attr == "encode"
    assert isinstance(encoded_candidate.func.value, ast.Name)
    assert encoded_candidate.func.value.id == candidate_parameter
    assert isinstance(comparison_argument, ast.Name), ast.unparse(comparison_argument)
    assert comparison_argument.id == find_comparison_hash_variable(function)


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
