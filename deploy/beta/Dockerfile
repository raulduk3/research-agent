# The swarm beta alone: the beta package and its fifteen pinned dependencies.
# Build from the repository root:
#   docker build -f deploy/beta/Dockerfile -t swarm-beta .
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src \
    RESEARCH_AGENT_BETA_DB=/var/lib/swarm/swarm.sqlite3
WORKDIR /app
# requirements.txt is the beta's dependency closure at the versions uv.lock
# pins, with hashes; tests/beta/test_deploy.py fails when the two drift.
COPY deploy/beta/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.txt \
    && useradd --create-home --uid 10001 app \
    && install --directory --owner=10001 --group=10001 /var/lib/swarm
COPY src/research_agent/__init__.py ./src/research_agent/__init__.py
COPY src/research_agent/beta ./src/research_agent/beta
RUN chown -R app:app /app/src
USER app
VOLUME /var/lib/swarm
EXPOSE 8000
ENTRYPOINT ["python", "-m", "research_agent.beta"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
