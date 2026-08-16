# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.14-alpine AS builder

RUN apk add --no-cache build-base cargo linux-headers

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.14-alpine AS runtime

RUN apk add --no-cache ca-certificates libgcc libstdc++ \
    && addgroup -S -g 10001 monitorubi \
    && adduser -S -D -H -u 10001 -G monitorubi monitorubi \
    && mkdir -p /app /data \
    && chown monitorubi:monitorubi /app /data

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MONITORUBI_DATABASE_PATH=/data/monitorUbi.db

COPY --from=builder --chown=monitorubi:monitorubi /app/.venv /app/.venv
COPY --chown=monitorubi:monitorubi monitorUbi /app/monitorUbi
COPY --chown=monitorubi:monitorubi config.toml README.md pyproject.toml /app/
COPY --chown=root:root docker-entrypoint.sh /usr/local/bin/monitorubi-entrypoint

RUN chmod 0755 /usr/local/bin/monitorubi-entrypoint

USER monitorubi
VOLUME ["/data"]
EXPOSE 8080

ENTRYPOINT ["monitorubi-entrypoint"]
CMD ["daemon"]
