FROM --platform=linux/amd64 python:3.12.12-slim-bookworm@sha256:2986c55feb36e6cae00fa1fefb454283e4b33f35e75ff8bdd123b134130be301

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN python -m pip install --no-cache-dir uv==0.8.22 \
    && uv sync --locked --no-dev --no-install-package research-agent \
    && useradd --create-home --uid 10001 app \
    && install --directory --owner=10001 --group=10001 /var/lib/research-agent/artifacts
COPY src ./src
# bin/build-image passes the commit it records in deploy/images.json; operator
# commands in the image name it as their producer (platform/producer.py).
ARG RESEARCH_AGENT_SOURCE_COMMIT
ENV RESEARCH_AGENT_SOURCE_COMMIT=${RESEARCH_AGENT_SOURCE_COMMIT}
USER app
ENTRYPOINT ["/app/.venv/bin/python", "-m", "research_agent"]
