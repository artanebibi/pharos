FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY services/rag-engine/requirements-cloud.txt /tmp/requirements-cloud.txt
RUN pip install -r /tmp/requirements-cloud.txt

FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --uid 10001 pharos
WORKDIR /app

COPY --chown=pharos:pharos services/rag-engine/ /app/services/rag-engine/
COPY --chown=pharos:pharos services/indexer/ /app/services/indexer/
COPY --chown=pharos:pharos runbooks/ /app/runbooks/

USER pharos

WORKDIR /app/services/rag-engine

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
