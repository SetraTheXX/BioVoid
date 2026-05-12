FROM python:3.13-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS runtime

COPY src/ ./src/
COPY main.py main_parallel.py ./
COPY scripts/run_phase6_api.py ./scripts/
COPY scripts/train_ml_model.py ./scripts/

RUN mkdir -p data/raw_pdb data/frames data/results data/docking data/models data/validation

EXPOSE 8000

ENV BIOVOID_WORKERS=4 \
    BIOVOID_LOG_LEVEL=INFO

CMD ["python", "scripts/run_phase6_api.py", "--host", "0.0.0.0", "--port", "8000"]
