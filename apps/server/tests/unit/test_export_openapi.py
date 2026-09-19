"""B-4 unit tests for the OpenAPI export that the contract drift check regenerates.

`app.export_openapi` builds the app through `create_app()`, renders `app.openapi()` as YAML with
keys sorted at every level and no timestamps, and writes it to `apps/server/docs/openapi.yaml`.
The drift check compares a fresh export with the committed file byte for byte, so the export must
list the health routes with their Pydantic response schemas, render identically on every run, and
build without a DATABASE_URL (CI's drift job has no database).
"""

import importlib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

EXPORT_DATABASE_URL = "postgresql+asyncpg://127.0.0.1:1/none"
HEALTH_LIVENESS_REF = "#/components/schemas/HealthLiveness"
HEALTH_READINESS_REF = "#/components/schemas/HealthReadiness"


def clear_settings_cache() -> None:
    """Drop the cached Settings so the next get_settings() reads the patched environment."""
    from app.core.settings import get_settings  # noqa: PLC0415

    get_settings.cache_clear()


def load_export_openapi_module() -> ModuleType:
    """Import app.export_openapi inside the test body, so a missing module fails the test."""
    return importlib.import_module("app.export_openapi")


def build_current_document() -> dict[str, Any]:
    """Return the document build_openapi_document() produces for the current app."""
    document: dict[str, Any] = load_export_openapi_module().build_openapi_document()
    return document


@pytest.fixture(autouse=True)
def export_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Patch DATABASE_URL and ENVIRONMENT and start every test with fresh settings."""
    monkeypatch.setenv("DATABASE_URL", EXPORT_DATABASE_URL)
    monkeypatch.setenv("ENVIRONMENT", "test")
    clear_settings_cache()
    yield
    clear_settings_cache()


def read_200_schema_ref(document: dict[str, Any], path: str) -> str:
    """Return the $ref of the JSON schema a GET on `path` declares for its 200 response."""
    ok_response = document["paths"][path]["get"]["responses"]["200"]
    schema_ref: str = ok_response["content"]["application/json"]["schema"]["$ref"]
    return schema_ref


def test_b4_document_lists_health_and_readiness_paths_with_get() -> None:
    """B-4: the exported document lists GET /health and GET /health/ready."""
    openapi_document = build_current_document()
    document_paths = openapi_document["paths"]

    assert "get" in document_paths["/health"]
    assert "get" in document_paths["/health/ready"]


def test_b4_document_components_define_both_health_schemas() -> None:
    """B-4: components.schemas carries HealthLiveness and HealthReadiness with their fields."""
    openapi_document = build_current_document()
    component_schemas = openapi_document["components"]["schemas"]
    liveness_properties = component_schemas["HealthLiveness"]["properties"]
    readiness_properties = component_schemas["HealthReadiness"]["properties"]

    assert set(liveness_properties) == {"status"}
    assert set(readiness_properties) == {"status", "db"}


def test_b4_health_routes_reference_their_response_models() -> None:
    """B-4: each health route's 200 response points at its Pydantic response model."""
    openapi_document = build_current_document()

    assert read_200_schema_ref(openapi_document, "/health") == HEALTH_LIVENESS_REF
    assert read_200_schema_ref(openapi_document, "/health/ready") == HEALTH_READINESS_REF


def test_b4_rendering_is_deterministic_and_round_trips() -> None:
    """B-4: rendering twice gives identical YAML, and parsing it gives back the document."""
    export_openapi_module = load_export_openapi_module()
    openapi_document = export_openapi_module.build_openapi_document()
    first_rendering = export_openapi_module.render_openapi_yaml(openapi_document)
    second_rendering = export_openapi_module.render_openapi_yaml(
        export_openapi_module.build_openapi_document()
    )

    assert isinstance(first_rendering, str)
    assert first_rendering == second_rendering
    assert yaml.safe_load(first_rendering) == openapi_document


def test_b4_rendered_yaml_sorts_keys_at_top_level_and_nested() -> None:
    """B-4: the top-level mapping and a nested schema's properties come out in sorted order."""
    export_openapi_module = load_export_openapi_module()
    openapi_document = export_openapi_module.build_openapi_document()
    parsed_document = yaml.safe_load(export_openapi_module.render_openapi_yaml(openapi_document))
    top_level_keys = list(parsed_document)
    readiness_property_names = list(
        parsed_document["components"]["schemas"]["HealthReadiness"]["properties"]
    )

    assert top_level_keys == sorted(top_level_keys)
    assert readiness_property_names == ["db", "status"]


def test_b4_main_writes_the_rendered_document_to_the_output_path(tmp_path: Path) -> None:
    """B-4: main(["--output", path]) returns 0 and writes exactly the rendered document."""
    export_openapi_module = load_export_openapi_module()
    output_path = tmp_path / "openapi.yaml"

    exit_code = export_openapi_module.main(["--output", str(output_path)])

    expected_yaml = export_openapi_module.render_openapi_yaml(
        export_openapi_module.build_openapi_document()
    )
    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8") == expected_yaml


def test_b4_document_builds_without_database_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B-4: the export builds with DATABASE_URL unset and no env file in the working directory."""
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.chdir(tmp_path)
    clear_settings_cache()

    document = build_current_document()

    assert "/health" in document["paths"]
    assert "/health/ready" in document["paths"]
