FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/expenses.db

WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY app/ ./app/

# Run as a non-root user. The data directory is created and owned by that user
# so the host-mounted volume is writable (a common Dokploy permission pitfall).
RUN adduser --disabled-password --gecos "" appuser \
 && mkdir -p /app/data \
 && chown -R appuser:appuser /app
USER appuser

# Persistent data location — mount a host volume here on the server.
VOLUME ["/app/data"]

CMD ["python", "-m", "app.main"]
