#!/usr/bin/env bash
set -euo pipefail
STACK="agis-orchestrator-olt"
COMPOSE="docker compose -p $STACK -f docker-compose.yml -f docker-compose.prod.yml"

echo "🔄  Construyendo imágenes…"
$COMPOSE pull
$COMPOSE build

echo "🚀  Desplegando…"
$COMPOSE up -d

# --------------  garantiza PostGIS (idempotente)  ---------------------
echo "⏳  Asegurando extensiones en la BD…"
$COMPOSE exec db psql -U postgres -d "${POSTGRES_DB:-olt}" -c \
  "CREATE EXTENSION IF NOT EXISTS postgis;
   CREATE EXTENSION IF NOT EXISTS timescaledb;"

echo
$COMPOSE ps
echo -e "\n✅  Producción arriba — UI: http://<HOST>/  |  API: http://<HOST>/api"
