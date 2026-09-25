"""B-11: both password-verifying services must reach bcrypt before any guard, not after one.

`app/core/security.py` removes the enumeration oracle inside `verify_password`: an unknown address
is compared against a dummy hash, so it costs the same quarter second a wrong password costs, and
`tests/unit/core/test_security.py` pins that structurally. None of that survives a caller that
decides not to call it. `sign_in_user` and `change_password` both spell the guard

    if not await verify_password(...) or user is None:

which is correct today only because Python evaluates the left operand of `or` first. Reordering it
to `if user is None or not await verify_password(...)` is functionally identical on every input,
is exactly what a reviewer simplifying a guard would write, and short-circuits bcrypt for an
address no account has: the unknown address then answers in microseconds while a wrong password
takes a quarter second, and the difference is a usable list of which addresses have accounts.
Every behavior test in the suite passes through that edit, because the responses are identical and
only the timing changes, and timing is not something a test can assert on a shared runner without
becoming flaky.

So the property is pinned on the source, as the verifier's own contract already is. What is
required is that the verification's result is bound to a name by an assignment statement, and that
the guard consults that name afterwards, so the call happens on every path through the function
whatever the guard then decides. That the checker really discriminates is proved in this file:
the two forms it must refuse are parsed from source strings here and asserted to be refused, and
the form the implementation should take is asserted to be accepted. No module on disk is edited to
prove it.
"""

import ast
import importlib
import inspect
import textwrap

import pytest

VERIFIER_NAME = "verify_password"
PASSWORD_VERIFYING_SERVICES = [
    ("app.services.auth.sign_in_user", "sign_in_user"),
    ("app.services.auth.change_password", "change_password"),
]

# The form under review: correct only by the left-to-right evaluation of `or`.
LEFT_OPERAND_SOURCE = '''
async def change_password(connection, user_id, session_id, current_password, new_password):
    """Replace the password after proving the caller knows it."""
    user = await lock_user_by_id(connection, user_id)
    stored_hash = user.password_hash if user else None
    if not await verify_password(current_password, stored_hash) or user is None:
        raise InvalidCredentialsError
'''

# The same guard with its operands swapped: identical answers, and no bcrypt call at all for an
# address no account has.
REORDERED_SOURCE = '''
async def change_password(connection, user_id, session_id, current_password, new_password):
    """Replace the password after proving the caller knows it."""
    user = await lock_user_by_id(connection, user_id)
    stored_hash = user.password_hash if user else None
    if user is None or not await verify_password(current_password, stored_hash):
        raise InvalidCredentialsError
'''

# An early return before the comparison: the same oracle, written as two statements.
EARLY_GUARD_SOURCE = '''
async def change_password(connection, user_id, session_id, current_password, new_password):
    """Replace the password after proving the caller knows it."""
    user = await lock_user_by_id(connection, user_id)
    if user is None:
        raise InvalidCredentialsError
    matched = await verify_password(current_password, user.password_hash)
    if not matched:
        raise InvalidCredentialsError
'''

# The form the implementation should take: compare first, decide after.
UNCONDITIONAL_SOURCE = '''
async def change_password(connection, user_id, session_id, current_password, new_password):
    """Replace the password after proving the caller knows it."""
    user = await lock_user_by_id(connection, user_id)
    stored_hash = user.password_hash if user else None
    matched = await verify_password(current_password, stored_hash)
    if not matched or user is None:
        raise InvalidCredentialsError
'''


def parse_async_function(source: str) -> ast.AsyncFunctionDef:
    """Return the parsed definition of one async function, dedented so its source stands alone."""
    parsed = ast.parse(textwrap.dedent(source)).body[0]
    assert isinstance(parsed, ast.AsyncFunctionDef)
    return parsed


def find_verification_await(function: ast.AsyncFunctionDef) -> ast.Await:
    """Return the one `await verify_password(...)` in the function, asserting there is one."""
    verifications = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == VERIFIER_NAME
    ]
    assert (
        len(verifications) == 1
    ), f"expected exactly one {VERIFIER_NAME} call, found {len(verifications)}"
    return verifications[0]


def contains_node(container: ast.AST, target: ast.AST) -> bool:
    """Return whether the target node appears anywhere inside the container."""
    return any(descendant is target for descendant in ast.walk(container))


def assert_verification_precedes_every_guard(source: str) -> None:
    """Assert the verification runs on every path, its result named before any guard reads it.

    Three things together say that. The awaited verification is not an operand of a boolean
    operator, so no neighbouring operand can short-circuit it. It is not inside the test of a
    conditional, so no branch can skip it. And it is the value of an assignment statement in the
    function body that precedes the first `if`, which then consults the name that assignment bound,
    so the decision is made from a comparison that already happened.
    """
    function = parse_async_function(source)
    verification = find_verification_await(function)

    for node in ast.walk(function):
        if isinstance(node, ast.BoolOp):
            assert not any(contains_node(operand, verification) for operand in node.values), (
                "the password comparison is an operand of a boolean operator, so a neighbouring "
                f"operand can short-circuit it: {ast.unparse(node)}"
            )
        if isinstance(node, (ast.If, ast.IfExp, ast.While)):
            assert not contains_node(node.test, verification), (
                "the password comparison sits inside the test of a conditional, so some input "
                f"never reaches bcrypt: {ast.unparse(node.test)}"
            )

    bindings = [
        index
        for index, statement in enumerate(function.body)
        if isinstance(statement, (ast.Assign, ast.AnnAssign)) and statement.value is verification
    ]
    assert len(bindings) == 1, (
        "the password comparison must be a statement of its own, binding its result to a name "
        f"before anything reads it: {ast.unparse(function)}"
    )
    binding_index = bindings[0]
    binding = function.body[binding_index]
    assert isinstance(binding, (ast.Assign, ast.AnnAssign)), ast.unparse(binding)
    target = binding.targets[0] if isinstance(binding, ast.Assign) else binding.target
    assert isinstance(target, ast.Name), ast.unparse(binding)

    guards = [
        index for index, statement in enumerate(function.body) if isinstance(statement, ast.If)
    ]
    assert guards, f"the function must still refuse a failed comparison: {ast.unparse(function)}"
    first_guard = function.body[guards[0]]
    assert isinstance(first_guard, ast.If)
    assert binding_index < guards[0], (
        "a guard runs before the password comparison, so an unknown account never costs a "
        f"bcrypt call: {ast.unparse(first_guard.test)}"
    )
    assert any(
        isinstance(node, ast.Name) and node.id == target.id for node in ast.walk(first_guard.test)
    ), (
        f"the first guard must decide on the comparison's result `{target.id}`: "
        f"{ast.unparse(first_guard.test)}"
    )


def test_the_checker_accepts_a_comparison_that_runs_before_the_guard() -> None:
    """The form the services should take passes, so an implementation can satisfy this check."""
    assert_verification_precedes_every_guard(UNCONDITIONAL_SOURCE)


@pytest.mark.parametrize(
    "rejected_source",
    [
        pytest.param(LEFT_OPERAND_SOURCE, id="verification-as-the-left-operand"),
        pytest.param(REORDERED_SOURCE, id="verification-as-the-right-operand"),
        pytest.param(EARLY_GUARD_SOURCE, id="guard-before-the-verification"),
    ],
)
def test_the_checker_rejects_every_guard_that_can_skip_the_comparison(rejected_source: str) -> None:
    """A check that accepted these would prove nothing about the services below.

    The left-operand form is what the services hold today, and it is refused as well as the
    reordered one: correct by evaluation order is a property one whitespace-level edit removes,
    and the edit is invisible in behavior.
    """
    with pytest.raises(AssertionError):
        assert_verification_precedes_every_guard(rejected_source)


@pytest.mark.parametrize(
    "module_name, function_name",
    [
        pytest.param(module_name, function_name, id=function_name)
        for module_name, function_name in PASSWORD_VERIFYING_SERVICES
    ],
)
def test_the_service_verifies_the_password_before_it_consults_any_guard(
    module_name: str, function_name: str
) -> None:
    """Both services must cost a real bcrypt comparison for an address no account has."""
    module = importlib.import_module(module_name)
    assert_verification_precedes_every_guard(inspect.getsource(getattr(module, function_name)))
