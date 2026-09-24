"""Checks of the three Railway service configurations (spec: Deployment, slice 08, IAN-341).

The template is never deployed (owner decision, 2026-09-24), so nothing else would notice a
configuration that names a Dockerfile that does not exist, a healthcheck path no route answers,
or an API that stops migrating before its replicas take traffic. Each check reads the committed
TOML and compares it with the code: the healthcheck paths against the routes the API factory and
the worker probe app actually register, and the Dockerfile paths against the files on disk,
resolved from the directory Railway builds each service in.
"""

import tomllib
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

SERVER_DIRECTORY = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = SERVER_DIRECTORY.parents[1]
API_CONFIG_PATH = SERVER_DIRECTORY / "railway.api.toml"
WORKER_CONFIG_PATH = SERVER_DIRECTORY / "railway.worker.toml"
WEB_CONFIG_PATH = REPOSITORY_ROOT / "apps" / "client" / "web" / "railway.toml"
MIGRATION_COMMAND = "alembic upgrade head"


def read_railway_config(config_path: Path) -> dict[str, Any]:
    """Parse one Railway TOML file, failing the calling test when the file is missing."""
    assert config_path.is_file(), f"{config_path.name} is missing"
    with config_path.open("rb") as config_file:
        return tomllib.load(config_file)


def list_worker_probe_paths() -> set[str]:
    """Return the paths the worker's probe app registers; building it touches no dependency."""
    from app.workers.health import create_worker_health_app  # noqa: PLC0415

    probe_app = create_worker_health_app(engine=None, redis=None)  # type: ignore[arg-type]
    return {route.path for route in probe_app.routes}  # type: ignore[attr-defined]


def test_the_api_builds_from_its_dockerfile_and_migrates_before_deploying() -> None:
    config = read_railway_config(API_CONFIG_PATH)
    build, deploy = config["build"], config["deploy"]

    assert build["builder"] == "DOCKERFILE"
    assert (SERVER_DIRECTORY / build["dockerfilePath"]).is_file()
    assert deploy["preDeployCommand"] == [MIGRATION_COMMAND]


def test_the_api_healthcheck_is_a_route_the_app_serves(server_app: FastAPI) -> None:
    deploy = read_railway_config(API_CONFIG_PATH)["deploy"]
    # The OpenAPI paths, because FastAPI keeps each included router as one opaque route object.
    served_paths = set(server_app.openapi()["paths"])

    assert deploy["healthcheckPath"] in served_paths


def test_the_api_healthcheck_is_liveness_so_a_database_outage_cannot_fail_a_deploy() -> None:
    """Readiness checks Postgres, and a Neon cold start would fail a deploy that changed code."""
    deploy = read_railway_config(API_CONFIG_PATH)["deploy"]

    assert deploy["healthcheckPath"] == "/health"


def test_the_worker_image_leaves_its_port_to_the_platform() -> None:
    """A baked WORKER_PORT would shadow the PORT Railway injects and health-checks."""
    dockerfile = (SERVER_DIRECTORY / "Dockerfile.worker").read_text()
    env_lines = [line for line in dockerfile.splitlines() if line.startswith("ENV ")]

    assert not any("WORKER_PORT=" in line for line in env_lines)
    assert "PORT" in dockerfile.split("HEALTHCHECK", 1)[1], "the healthcheck must follow PORT"


def test_the_worker_builds_from_its_own_dockerfile_and_never_migrates() -> None:
    config = read_railway_config(WORKER_CONFIG_PATH)
    build, deploy = config["build"], config["deploy"]

    assert build["builder"] == "DOCKERFILE"
    assert build["dockerfilePath"] == "Dockerfile.worker"
    assert (SERVER_DIRECTORY / build["dockerfilePath"]).is_file()
    assert "preDeployCommand" not in deploy
    assert deploy["healthcheckPath"] in list_worker_probe_paths()


def test_the_web_builds_from_the_repository_root_and_checks_its_nitro_route() -> None:
    config = read_railway_config(WEB_CONFIG_PATH)
    build, deploy = config["build"], config["deploy"]

    assert build["builder"] == "DOCKERFILE"
    assert (REPOSITORY_ROOT / build["dockerfilePath"]).is_file()
    assert deploy["healthcheckPath"] == "/api/health"
    assert (REPOSITORY_ROOT / "apps/client/web/server/api/health.get.ts").is_file()
    assert "preDeployCommand" not in deploy


@pytest.mark.parametrize("config_path", [API_CONFIG_PATH, WORKER_CONFIG_PATH, WEB_CONFIG_PATH])
def test_every_service_restarts_on_failure_and_carries_no_variables(config_path: Path) -> None:
    """Variables and secrets are set on the service, never committed in its config file."""
    config = read_railway_config(config_path)

    assert config["deploy"]["restartPolicyType"] == "ON_FAILURE"
    assert set(config) <= {"build", "deploy"}, "an [env] or [variables] block does not belong here"
