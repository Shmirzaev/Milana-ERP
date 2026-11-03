FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        gcc libpq-dev libpq5 curl fonts-dejavu-core \
    && pip install --no-cache-dir setuptools==84.2.1 \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN mkdir -p /app/storage/barcodes /app/storage/model_files /app/storage/sales_order_files \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "PYTHONPATH=/app:/app/backend alembic -c /app/alembic.ini upgrade head && PYTHONPATH=/app:/app/backend uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers ${WEB_CONCURRENCY:-2}"]
