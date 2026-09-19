"""Unit tests for the engine's Postgres TLS connect arguments (Copilot 4052684562, spec Security).

The spec's Security section requires Postgres over TLS with certificate verification
(`sslmode=verify-full`), with an optional `DATABASE_CA_CERT` for a private CA. The engine factory
builds its asyncpg `connect_args` through `app.db.engine.build_connect_args(settings)`, so these
tests assert on that dict: staging and production carry an `ssl.SSLContext` that requires a
verified certificate and a matching hostname, a configured CA file is loaded into that context,
development and test (local Postgres without TLS) carry no `ssl` key, and the connect timeout and
statement timeout stay present in every environment.
"""

import shutil
import ssl
import subprocess
from pathlib import Path

import pytest

from app.core.settings import Settings
from app.db.engine import build_connect_args

UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://127.0.0.1:1/none"
PEM_CERTIFICATE_END = "-----END CERTIFICATE-----"
MISSING_CA_SKIP_REASON = "IAN-124: no openssl CLI and no system CA bundle to build a CA file from"


@pytest.fixture(autouse=True)
def clear_tls_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's own DATABASE_CA_CERT or ENVIRONMENT from leaking into Settings."""
    monkeypatch.delenv("DATABASE_CA_CERT", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)


def build_settings(environment: str, database_ca_cert: str | None = None) -> Settings:
    """Build Settings directly for one environment and an optional CA file path."""
    return Settings(
        database_url=UNREACHABLE_DATABASE_URL,
        environment=environment,
        database_ca_cert=database_ca_cert,
    )


def generate_self_signed_ca(directory: Path) -> Path | None:
    """Write a throwaway self-signed CA certificate with the openssl CLI, or return None."""
    openssl_path = shutil.which("openssl")
    if openssl_path is None:
        return None
    certificate_path = directory / "private-ca.pem"
    key_path = directory / "private-ca-key.pem"
    completed_process = subprocess.run(  # noqa: S603 (fixed argv, openssl from PATH)
        [
            openssl_path,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key_path),
            "-out",
            str(certificate_path),
            "-days",
            "1",
            "-subj",
            "/CN=template-test-private-ca",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
        ],
        capture_output=True,
        check=False,
    )
    if completed_process.returncode != 0 or not certificate_path.exists():
        return None
    return certificate_path


def copy_first_system_ca(directory: Path) -> Path | None:
    """Copy the first certificate of the system CA bundle into a temporary PEM file."""
    bundle_path = ssl.get_default_verify_paths().cafile
    if bundle_path is None or not Path(bundle_path).is_file():
        return None
    bundle_text = Path(bundle_path).read_text()
    if PEM_CERTIFICATE_END not in bundle_text:
        return None
    first_certificate = bundle_text.split(PEM_CERTIFICATE_END)[0] + PEM_CERTIFICATE_END + "\n"
    certificate_path = directory / "system-ca.pem"
    certificate_path.write_text(first_certificate[first_certificate.index("-----BEGIN") :])
    return certificate_path


@pytest.fixture
def ca_certificate_path(tmp_path: Path) -> Path:
    """Return a temporary PEM file holding one CA certificate, or skip naming IAN-124."""
    certificate_path = generate_self_signed_ca(tmp_path) or copy_first_system_ca(tmp_path)
    if certificate_path is None:
        pytest.skip(MISSING_CA_SKIP_REASON)
    return certificate_path


def assert_timeouts_present(connect_args: dict) -> None:
    """Assert the connect timeout and the statement timeout survive the TLS change."""
    assert "timeout" in connect_args
    assert connect_args["timeout"] > 0
    assert "statement_timeout" in connect_args["server_settings"]


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_copilot_4052684562_deployed_environments_verify_the_postgres_certificate(
    environment: str,
) -> None:
    """Copilot 4052684562, spec Security (sslmode=verify-full): staging and production verify."""
    connect_args = build_connect_args(build_settings(environment))

    tls_context = connect_args.get("ssl")
    assert isinstance(tls_context, ssl.SSLContext), connect_args
    assert tls_context.verify_mode == ssl.CERT_REQUIRED
    assert tls_context.check_hostname is True
    assert_timeouts_present(connect_args)


def test_copilot_4052684562_database_ca_cert_is_loaded_into_the_tls_context(
    ca_certificate_path: Path,
) -> None:
    """Copilot 4052684562, spec Security (DATABASE_CA_CERT): the private CA file is trusted."""
    connect_args = build_connect_args(
        build_settings("production", database_ca_cert=str(ca_certificate_path))
    )

    tls_context = connect_args.get("ssl")
    assert isinstance(tls_context, ssl.SSLContext), connect_args
    assert tls_context.verify_mode == ssl.CERT_REQUIRED
    assert tls_context.check_hostname is True
    assert tls_context.cert_store_stats()["x509_ca"] >= 1
    expected_ca_der = ssl.PEM_cert_to_DER_cert(ca_certificate_path.read_text())
    assert expected_ca_der in tls_context.get_ca_certs(binary_form=True)
    assert_timeouts_present(connect_args)


@pytest.mark.parametrize("environment", ["development", "test"])
def test_copilot_4052684562_local_environments_connect_without_tls(environment: str) -> None:
    """Copilot 4052684562, spec Security: local Postgres has no TLS, so no ssl key is passed."""
    connect_args = build_connect_args(build_settings(environment))

    assert "ssl" not in connect_args
    assert_timeouts_present(connect_args)
