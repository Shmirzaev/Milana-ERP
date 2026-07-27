FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/storage/barcodes /app/storage/model_files /app/storage/sales_order_files \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "PYTHONPATH=/app:/app/backend alembic -c /app/alembic.ini upgrade head && PYTHONPATH=/app:/app/backend uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
