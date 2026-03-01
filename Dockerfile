# ─── Stage 1: build ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim

LABEL org.opencontainers.image.title="GAPI" \
      org.opencontainers.image.description="Game API — random game picker web app" \
      org.opencontainers.image.source="https://github.com/mattam1234/GAPI"

# Runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN addgroup --system gapi && adduser --system --ingroup gapi gapi

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY --chown=gapi:gapi . .

USER gapi

# Runtime configuration via environment variables
ENV FLASK_APP=gapi_gui.py \
    FLASK_ENV=production \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

# Use gunicorn in production; fall back to Flask dev server if not installed
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 120 gapi_gui:app 2>/dev/null || python gapi_gui.py --host 0.0.0.0 --port 5000"]
