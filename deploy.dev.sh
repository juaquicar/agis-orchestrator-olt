#!/usr/bin/env bash
# deploy.dev.sh – Despliegue en desarrollo con .env limpio, DB_DSN dinámico y logs

set -euo pipefail

echo "🔑 Cargando variables de entorno desde .env"
if [ -f .env ]; then
  while IFS='=' read -r raw_key raw_val; do
    # trim espacios
    key="${raw_key#"${raw_key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    # eliminar comentarios en línea y luego trim
    val="${raw_val%%\#*}"
    val="${val#"${val%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    # saltar vacías o comentarios completos
    [[ -z "$key" || "$key" == \#* ]] && continue
    # sólo nombres válidos
    if [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      export "$key=$val"
    else
      echo "⚠️  Ignorado: clave inválida '$key'"
    fi
  done < .env
else
  echo "ℹ️  No se encontró fichero .env"
fi

# Reconstruir DB_DSN si no estaba en .env
if [ -z "${DB_DSN:-}" ] && [ -n "${POSTGRES_USER:-}" ]; then
  export DB_DSN="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-olt}"
  echo "🔧 DB_DSN construida: $DB_DSN"
fi

LOG_DIR="logs"
mkdir -p "$LOG_DIR"
# borrar logs previos
rm -f "${LOG_DIR:?}"/*.log

echo "🔨 Arrancando contenedores (desarrollo)…"
docker compose up --build --remove-orphans -d

echo "⏳ Esperando inicialización…"
sleep 5

echo "✅ Estado de los contenedores:"
docker compose ps

echo "📥 Volcando logs a ${LOG_DIR}/"
for svc in collector api db redis nginx; do
  docker compose logs --no-color "$svc" > "${LOG_DIR}/${svc}.log" 2>&1 \
    && echo "   • ${svc}.log"
done

echo
echo "🖥️  Abriendo tail de collector y api…"
docker compose logs -f collector api
