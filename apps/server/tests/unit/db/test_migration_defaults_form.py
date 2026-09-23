"""R-328: every column default in a revision is a bare constant or an explicit SQL expression.

The guard exists because a default written as a quoted expression, `server_default="now()"` or
`sa.text("'now()'")`, is accepted by the migration and then stores the literal text rather than
the time, which nothing notices until a row is read back months later. This test reads the
revision files as source rather than importing them, because the form is what the rule constrains
and an imported module has already lost the difference between the two spellings.
"""

import ast
import re
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_PATH = SERVER_ROOT / "migrations" / "versions"
SERVER_DEFAULT_KEYWORD = "server_default"
SQL_KEYWORDS = frozenset(
    {
        "CURRENT_TIMESTAMP",
        "CURRENT_DATE",
        "CURRENT_TIME",
        "LOCALTIME",
        "LOCALTIMESTAMP",
        "CURRENT_USER",
        "SESSION_USER",
        "CURRENT_SCHEMA",
    }
)
NESTED_QUOTES = ("'", '"')


def find_revision_paths() -> list[Path]:
    """Return every revision module, so a revision added later is covered without an edit here."""
    return sorted(path for path in VERSIONS_PATH.glob("*.py") if path.name != "__init__.py")


def collect_server_default_nodes(revision_path: Path) -> list[ast.expr]:
    """Return the value node of every `server_default=` keyword in one revision."""
    tree = ast.parse(revision_path.read_text(encoding="utf-8"), filename=str(revision_path))
    return [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == SERVER_DEFAULT_KEYWORD
    ]


def has_nested_quotes(value: str) -> bool:
    """Identify an already quoted value without rejecting quotes inside SQL expressions."""
    stripped = value.strip()
    return bool(stripped) and stripped[0] in NESTED_QUOTES


def is_sql_expression(value: str) -> bool:
    """Recognize SQL calls, casts, special values, and operators in a bare string."""
    return (
        "(" in value
        or "::" in value
        or value.strip().upper() in SQL_KEYWORDS
        or bool(re.search(r"\b(?:SELECT|INTERVAL|CASE|NEXT\s+VALUE)\b", value, re.IGNORECASE))
        or bool(re.search(r"\d\s*[+*/-]\s*\d|\|\|", value))
    )


def collect_attribute_names(node: ast.expr) -> list[str]:
    """Read the complete attribute chain so only explicit SQLAlchemy calls qualify."""
    names = []
    while isinstance(node, ast.Attribute):
        names.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.append(node.id)
    return list(reversed(names))


def describe_constant_violation(value: str) -> str | None:
    """Reject constants that contain quoting or recognizable SQL syntax."""
    if has_nested_quotes(value):
        return f"a constant carrying nested quotes: {value!r}"
    if is_sql_expression(value):
        return f"a SQL expression written as a bare string: {value!r}"
    return None


def describe_default_violation(default_node: ast.expr) -> str | None:
    """Return why a default violates the required source form."""
    if isinstance(default_node, ast.Constant) and isinstance(default_node.value, str):
        return describe_constant_violation(default_node.value)
    if not isinstance(default_node, ast.Call):
        return f"neither a bare string nor an explicit SQL expression: {ast.dump(default_node)}"
    names = collect_attribute_names(default_node.func)
    if names == ["sa", "text"]:
        return describe_text_violation(default_node)
    if len(names) >= 3 and names[:2] == ["sa", "func"]:
        return None
    return f"an unrecognized SQL expression: {ast.dump(default_node.func)}"


def describe_text_violation(default_node: ast.Call) -> str | None:
    """Require an inspectable SQL expression rather than an already quoted literal."""
    if len(default_node.args) != 1 or default_node.keywords:
        return "sa.text must contain one explicit SQL string"
    argument = default_node.args[0]
    if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
        return "sa.text must contain a literal SQL string"
    if has_nested_quotes(argument.value):
        return f"a SQL expression carrying nested quotes: {argument.value!r}"
    return None


def test_every_column_default_in_every_revision_takes_an_allowed_form() -> None:
    """R-328: constants stay bare strings and SQL expressions go through sa.text or sa.func.

    The revisions are collected inside the test rather than at parametrize time, so an empty
    versions directory fails here rather than collapsing into a collected-nothing pass.
    """
    revision_paths = find_revision_paths()
    assert revision_paths, f"no revision modules found under {VERSIONS_PATH}"

    violations = [
        f"{revision_path.name}: {violation}"
        for revision_path in revision_paths
        for default_node in collect_server_default_nodes(revision_path)
        if (violation := describe_default_violation(default_node)) is not None
    ]

    assert not violations, violations
