# API image (R-351): FastAPI served by uvicorn as the non-root `app` user.
# The builder stage installs the locked dependencies with uv; the runtime stage copies only the
# virtual environment and the application code. Configuration arrives as environment variables at
# run time, never as build arguments (R-102). Build context: apps/server.
FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app/ app/
# The migration chain ships in the image because the image is what runs it: the compose `migrate`
# service, and Railway's preDeployCommand from slice 08, both invoke `alembic upgrade head` on
# this image rather than on a checkout.
COPY alembic.ini ./
COPY migrations/ migrations/
RUN uv sync --frozen --no-dev

FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" PORT=3001
RUN useradd --create-home --uid 10001 app
COPY --from=builder --chown=app:app /app /app
USER app
EXPOSE 3001
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=2)" || exit 1
# --proxy-headers trusts X-Forwarded-For only from FORWARDED_ALLOW_IPS, set at run time to the
# web service's private network (spec: Client IP trust chain); never "*".
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port \"$PORT\" --proxy-headers"]
