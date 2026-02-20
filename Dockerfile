# Trend Analyzer - Django + Celery
FROM python:3.11-slim-bookworm

# Java: PyKomoran(한국어 형태소 분석) 의존
# git for pip install from git (dcinside-read-api)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    git \
    libpq-dev \
    openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Non-root user
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Default: gunicorn (override in docker-compose for celery)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "trend_analyzer.wsgi:application"]
