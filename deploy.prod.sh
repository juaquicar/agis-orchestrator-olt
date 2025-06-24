#!/usr/bin/env bash
# deploy.prod.sh – Despliegue en producción SIN override de dev, con mount de config

set -euo pipefail

# 1) Definir ficheros Compose (sin el override de dev)
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)

# 2) Cargar .env.prod o usar .env si falta
echo "🔑 Cargando variables de entorno (producción)…"
if [ -f .env.prod ]; then
  ENV_FILE=".env.prod"
elif [ -f .env ]; then
  echo "⚠️  .env.prod no existe, usando .env"
  ENV_FILE=".env"
else
  echo "❌ No existe ni .env.prod ni .env. Cancelo."
  exit 1
fi

while IFS='=' read -r raw_key raw_val; do
  key="${raw_key#"${raw_key%%[![:space:]]*}"}"
  key="${key%"${key##*[![:space:]]}"}"
  val="${raw_val%%\#*}"
  val="${val#"${val%%[![:space:]]*}"}"
  val="${val%"${val##*[![:space:]]}"}"
  [[ -z "$key" || "$key" == \#* ]] && continue
  if [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    export "$key=$val"
  else
    echo "⚠️  Ignorado: clave inválida '$key'"
  fi
done < "$ENV_FILE"

# 3) Comprobar que el config está donde debe
CONFIG_FILE="./collector/config/olts.yaml"
if [ ! -f "$CONFIG_FILE" ]; then
  echo "❌ No se encontró $CONFIG_FILE. Asegúrate de tener tu olts.yaml ahí."
  exit 1
fi

# 4) Pull de imágenes
echo "🚀 Pull de las últimas imágenes…"
docker compose "${COMPOSE_FILES[@]}" pull

# 5) Up en detach, forzando recreate y sin orphans
echo "🔨 Arrancando servicios en producción…"
docker compose "${COMPOSE_FILES[@]}" up -d --force-recreate --remove-orphans

# 6) Esperar arrancar
echo "⏳ Esperando inicialización…"
sleep 15

# 7) Estado
echo "✅ Estado de los servicios:"
docker compose "${COMPOSE_FILES[@]}" ps

# 8) Logs timestamped
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_DIR="logs/${TIMESTAMP}"
mkdir -p "$LOG_DIR"
echo "📥 Volcando logs de collector y api en ${LOG_DIR}/"
for svc in collector api; do
  docker compose "${COMPOSE_FILES[@]}" logs --no-color "$svc" \
    > "${LOG_DIR}/${svc}.log"
  echo "   • ${svc}.log"
done

# 9) Limpiar imágenes dangling
echo "🧹 Limpiando imágenes dangling…"
docker image prune -f

echo
echo "🎉 Despliegue completado. Logs en ${LOG_DIR}/"
