# ─────────────────────────────────────────────────────────────────────────────
# Multi-stage Dockerfile for PathogenIQ API
#
# Stage 1 (builder): installs all Python dependencies into a virtual env
# Stage 2 (development): inherits builder, adds dev tools, hot-reload via uvicorn
# Stage 3 (production): minimal image, no dev tools, no source mount
#
# Why multi-stage?
#   - Keeps the final production image small (no build tools, no compiler)
#   - Development stage has everything needed for hot-reload and debugging
#   - Single Dockerfile handles both environments
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System libs needed to compile asyncpg (PostgreSQL C driver)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only the manifest first — Docker layer cache skips pip install
# on subsequent builds if pyproject.toml hasn't changed.
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[dev]"


# ── Stage 2: development ──────────────────────────────────────────────────────
FROM python:3.12-slim AS development

WORKDIR /app

# Runtime system libraries only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Pull installed packages from builder stage
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Source is volume-mounted in docker-compose, but copy it here so the image
# works standalone (e.g., in CI without a volume mount)
COPY . .

EXPOSE 8000

# --reload watches for file changes; disabled in production stage
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


# ── Stage 3: production ───────────────────────────────────────────────────────
FROM python:3.12-slim AS production

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY . .

# Non-root user for security (never run production containers as root)
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app

COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

USER appuser

EXPOSE 8000

# Starts both the API (uvicorn) and the ARQ worker in one container.
# The worker handles background pipeline jobs enqueued via the API.
CMD ["/app/start.sh"]
