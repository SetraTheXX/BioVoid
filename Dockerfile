FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS frontend-build

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91 AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt

FROM base AS runtime

COPY src/ ./src/
COPY main.py main_parallel.py ./
COPY scripts/run_phase6_api.py ./scripts/
COPY scripts/train_ml_model.py ./scripts/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist/

RUN mkdir -p data/raw_pdb data/frames data/results data/docking data/models data/validation

EXPOSE 8000

ENV BIOVOID_WORKERS=1 \
    BIOVOID_LOG_LEVEL=INFO

# A standalone image is local-only by default. Compose opts into the
# container-network bind while keeping the host port on loopback.
CMD ["python", "scripts/run_phase6_api.py", "--host", "127.0.0.1", "--port", "8000"]
