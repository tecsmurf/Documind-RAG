# Production image (Render builds this from the repo root).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini backend/start.sh ./

# Run as an unprivileged user; the app never writes to disk.
RUN useradd --system --uid 10001 --no-create-home documind && chmod +x start.sh
USER documind

EXPOSE 8000
CMD ["./start.sh"]
