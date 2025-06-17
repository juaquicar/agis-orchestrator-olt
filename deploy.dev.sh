#!/usr/bin/env bash
set -euo pipefail

cp -n .env.example .env           # crea .env sólo si no existe

cat > docker-compose.override.yml <<'EOF'
services:
  api:
    volumes:
      - ./api:/app/api
    command: >
      uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
  collector:
    volumes:
      - ./collector:/app
    command: >
      celery -A tasks worker -B --loglevel=info --autoreload
  redis:
    ports: []                     # sin puerto al host
EOF

docker compose pull
docker compose up -d --build

# --------------  crea PostGIS si el volumen ya existía  ---------------
echo "⏳  Verificando extensiones PostGIS y Timescale…"
docker compose exec db psql -U postgres -d "${POSTGRES_DB:-olt}" -c \
  "CREATE EXTENSION IF NOT EXISTS postgis;
   CREATE EXTENSION IF NOT EXISTS timescaledb;"

docker compose ps
echo -e "\n🟢  DEV listo → http://localhost   |   API → http://localhost/api"
