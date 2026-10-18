# ---- frontend build ----------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx tsc -b && npx vite build

# ---- runtime -----------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DATA_DIR=/data SAMPLE_DIR=/app/data/sample SANCTIONS_DIR=/app/data/sanctions STATIC_DIR=/app/frontend/dist
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY scripts/download_sanctions.py scripts/download_sanctions.py
# Sanctions lists are downloaded at build time and cached in the image (OFAC SDN + EU consolidated).
# A failed download does not fail the build; the app then reports the lists as unavailable.
RUN python scripts/download_sanctions.py /app/data/sanctions || echo "sanctions download failed; continuing"
COPY backend/ backend/
COPY data/sample/ data/sample/
COPY --from=web /web/dist frontend/dist
RUN useradd --system --uid 10001 app && mkdir -p /data && chown app /data
USER app
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
