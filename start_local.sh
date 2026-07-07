#!/usr/bin/env bash
# SepraAI v2.7 — Local Bootstrapper
# Sets up directories, launches backing services, and initialises database triggers.

set -e

echo "=== SepraAI v2.7 Local Environment Bootstrapper ==="

# 1. Setup local mount volumes
echo "Initializing local volume folders..."
mkdir -p ./infrastructure/volumes/postgres ./infrastructure/volumes/minio

# 2. Spin up backing containers (Postgres, Redis, MinIO)
echo "Spinning up backing Docker infrastructure..."
docker compose -f sepraai-backend/infrastructure/docker-compose.yml up -d postgres redis minio

# 3. Wait for PostgreSQL connection availability
echo "Waiting for PostgreSQL container availability..."
until docker exec sepraai-postgres pg_isready -U sepraai >/dev/null 2>&1; do
    echo -n "."
    sleep 2
done
echo " PostgreSQL container is ready!"

# 4. Bootstrap tables and apply GCM immutability DDL triggers
echo "Executing database initialization script..."
export PYTHONPATH=./sepraai-backend
python3 sepraai-backend/db_init.py

echo "=== System Bootstrapped Successfully! ==="
echo "Backing services are up. You can now launch workers and FastAPI Gateway:"
echo " - Run API Gateway: uvicorn api.main:app --reload"
echo " - Run ARQ Workers: arq orchestration.arq_broker.WorkerSettings"
