# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH=/usr/local/bin:$PATH

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (better layer caching)
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy app
COPY . .

# Expose port
EXPOSE 80

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Default envs (can be overridden)
ENV FLASK_ENV=production \
    DATABASE_URL=sqlite:////data/ai_tools_hub.db \
    SECRET_KEY=change-me

# Persist application data (SQLite DB lives here)
VOLUME ["/data"]

# Run with gunicorn
CMD ["gunicorn", "-w", "6", "--worker-class", "gevent", "--worker-connections", "1000", "-b", "0.0.0.0:80", "app:app"]


