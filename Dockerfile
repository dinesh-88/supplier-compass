# One image for linux/amd64 (Nebius serverless endpoints). Build with:
#   docker buildx build --platform linux/amd64 -t supplier-compass .

# ---- frontend build ----------------------------------------------------------
# The bundle is platform-independent, so this stage runs natively on the build machine (no emulation).
FROM --platform=$BUILDPLATFORM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx tsc -b && npx vite build

# ---- runtime -----------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080 DATA_DIR=/tmp/data \
    SAMPLE_DIR=/app/data/sample SANCTIONS_DIR=/app/data/sanctions STATIC_DIR=/app/frontend/dist
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY scripts/download_sanctions.py scripts/download_sanctions.py
# Sanctions lists are downloaded at build time and cached in the image (OFAC SDN + EU consolidated).
# A failed download does not fail the build; the app then reports the lists as unavailable.
RUN python scripts/download_sanctions.py /app/data/sanctions || echo "sanctions download failed; continuing"
COPY backend/app/ backend/app/
# The challenge sample ships inside the image, so it loads even after the data disk is wiped.
COPY data/sample/ data/sample/
COPY --from=web /web/dist frontend/dist
RUN useradd --system --uid 10001 --home-dir /tmp app
USER 10001
WORKDIR /app/backend
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8080\")}/health')"
# Datasets live in DATA_DIR (default /tmp/data), which is created at startup and may be wiped on restart.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8080}\" --proxy-headers --forwarded-allow-ips '*'"]
