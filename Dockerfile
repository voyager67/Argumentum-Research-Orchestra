# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ARGUMENTUM_DATA_DIR=/data

ARG ARGUMENTUM_EXTRAS="server,all-documents"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 argumentum \
    && useradd --system --uid 10001 --gid argumentum --home-dir /app --shell /usr/sbin/nologin argumentum \
    && mkdir -p /data/runs /data/sandbox \
    && chown -R argumentum:argumentum /app /data

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[${ARGUMENTUM_EXTRAS}]"

USER argumentum
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/ready', timeout=3)" || exit 1

CMD ["uvicorn", "argumentum.server.api:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
