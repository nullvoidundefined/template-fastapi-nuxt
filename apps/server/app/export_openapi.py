"""Writes the API's OpenAPI document to `apps/server/docs/openapi.yaml` (spec B-4, the type flow).

Run as `uv run python -m app.export_openapi [--output PATH]`. The document is built from the same
`create_app()` uvicorn runs, and rendered with keys sorted at every level and no timestamps, so an
unchanged API always exports byte-identical YAML and the CI drift check fails only on real change.
Building the document never connects to Postgres, so when DATABASE_URL is unset (the drift job
has no database) a placeholder URL with no credentials stands in for it.
"""

import argparse
import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[1] / "docs" / "openapi.yaml"
PLACEHOLDER_DATABASE_URL = "postgresql+asyncpg://127.0.0.1:1/openapi-export"


def build_openapi_document() -> dict[str, Any]:
    """Build the app through its factory and return the OpenAPI document FastAPI generates."""
    os.environ.setdefault("DATABASE_URL", PLACEHOLDER_DATABASE_URL)
    from app.main import create_app  # noqa: PLC0415 (settings must see the placeholder first)

    return create_app().openapi()


def render_openapi_yaml(document: dict[str, Any]) -> str:
    """Render the document as YAML with every mapping's keys sorted."""
    return yaml.safe_dump(document, sort_keys=True, allow_unicode=True, width=100)


def main(argv: list[str] | None = None) -> int:
    """Write the rendered document to the output path and return the exit status."""
    parser = argparse.ArgumentParser(description="Export the OpenAPI document as YAML.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    arguments = parser.parse_args(argv)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(render_openapi_yaml(build_openapi_document()), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
