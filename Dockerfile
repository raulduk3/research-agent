FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN python -m pip install --no-cache-dir uv==0.8.22 \
    && uv sync --locked --no-dev --no-install-package research-agent \
    && useradd --create-home --uid 10001 app \
    && install --directory --owner=10001 --group=10001 /var/lib/research-agent/artifacts
COPY src ./src
COPY docs/evidence/source-pilot ./docs/evidence/source-pilot
USER app
ENTRYPOINT ["/app/.venv/bin/python", "-m", "research_agent"]
