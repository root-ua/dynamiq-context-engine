# syntax=docker/dockerfile:1.7
#
# FastAPI backend. Single Python base; `dev` and `runner` targets share
# dependencies but differ on whether the project is installed editable
# + whether the app runs as root (dev) or a dedicated user (prod).

FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      libpq-dev \
      curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --upgrade pip setuptools wheel

# ---------------------------------------------------------------------------
# Dev target — editable install + dev deps (pytest, ruff, mypy). Source
# is volume-mounted by docker-compose.
# ---------------------------------------------------------------------------
FROM base AS dev
RUN pip install -e ".[dev]"
COPY . .
RUN chmod +x docker-entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------------
# Production runtime — no dev deps, non-root user, gunicorn+uvicorn.
# ---------------------------------------------------------------------------
FROM base AS runner
RUN pip install "." "gunicorn>=22.0"
COPY . .
RUN chmod +x docker-entrypoint.sh \
 && groupadd --system --gid 1001 app \
 && useradd --system --uid 1001 --gid app --create-home appuser \
 && chown -R appuser:app /app
USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
# Gunicorn with uvicorn workers — mature choice for production FastAPI.
# Worker count defaults to 2×CPU+1 via gunicorn's own logic when
# WEB_CONCURRENCY isn't set; Render sets it based on the instance plan.
CMD ["gunicorn", "app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-"]
