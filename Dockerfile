# ---------------------------------------------------------------------------
# Single-service production image.
#
# Stage 1 builds the React app; stage 2 runs FastAPI and serves that build from
# the same origin. One URL, no CORS, one thing to deploy.
# ---------------------------------------------------------------------------

FROM node:20-alpine AS ui

WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

COPY frontend/ ./
# No VITE_API_BASE: the client then uses same-origin relative paths.
RUN npm run build


FROM python:3.12-slim AS app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
# config.py resolves DATA_DIR as <parent of backend>/data, so /data it is.
COPY data/ /data/

# The built UI is served by FastAPI from backend/static (see app/main.py).
COPY --from=ui /ui/dist ./static

# Free hosting tiers have an ephemeral filesystem; the SQLite file is
# recreated on boot and the demo is reproducible from the committed source
# files, so nothing is lost on a restart.
ENV DATABASE_URL=sqlite:////app/migration.db \
    ENVIRONMENT=production \
    LLM_PROVIDER=none \
    PORT=8000

EXPOSE 8000

# Regenerate the demo sources on boot so the image is self-sufficient even if
# data/ was not committed, then serve.
CMD ["sh", "-c", "python seed_demo.py && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
