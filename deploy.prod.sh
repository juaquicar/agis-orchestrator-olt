#!/usr/bin/env bash
# deploy.prod.sh – Despliegue en producción (compose + prod override)
# Uso:
#   ./deploy.prod.sh [opciones]
#
# Opciones:
#   -B | --build         Fuerza reconstrucción (docker compose build --no-cache)
#   -t | --tag TAG       Exporta IMAGE_TAG=TAG (para interpolar en compose)
#   -R | --reset         Baja stack antes (down -v --remove-orphans) ⚠️ borra volúmenes
#   -P | --no-pull       No ejecutar 'docker compose pull'
#   -L | --logs          Tras el up, volcar logs a carpeta con timestamp
#   -h | --help          Muestra esta ayuda

set -euo pipefail

# ----------------------------
# Config básica del proyecto
# ----------------------------
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)
CONFIG_FILE="./collector/config/olts.yaml"   # Ajusta si tu ruta cambia
ENV_FILE=""
DO_BUILD=0
DO_RESET=0
DO_PULL=1
DO_LOGS=0
IMAGE_TAG_ARG=""

log() { printf "%b\n" "$*"; }
die() { printf "❌ %b\n" "$*\n" >&2; exit 1; }

usage() {
  sed -n '1,30p' "$0" | sed -n '1,30p'
  exit 0
}

# ----------------------------
# Parseo de argumentos
# ----------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -B|--build) DO_BUILD=1; shift ;;
    -t|--tag)   [[ $# -ge 2 ]] || die "Falta valor para --tag"
                IMAGE_TAG_ARG="$2"; shift 2 ;;
    -R|--reset) DO_RESET=1; shift ;;
    -P|--no-pull) DO_PULL=0; shift ;;
    -L|--logs)  DO_LOGS=1; shift ;;
    -h|--help)  usage ;;
    *) die "Opción desconocida: $1 (usa -h)";;
  esac
done

# ----------------------------
# 1) Cargar .env.prod o .env
# ----------------------------
log "🔑 Cargando variables de entorno (producción)…"
if [[ -f .env.prod ]]; then
  ENV_FILE=".env.prod"
elif [[ -f .env ]]; then
  log "⚠️  .env.prod no existe, usando .env"
  ENV_FILE=".env"
else
  die "No existe ni .env.prod ni .env"
fi

# Exportar variables del fichero .env* (sin pisar líneas comentadas)
while IFS='=' read -r raw_key raw_val; do
  key="${raw_key#"${raw_key%%[![:space:]]*}"}"
  key="${key%"${key##*[![:space:]]}"}"
  val="${raw_val%%\#*}"
  val="${val#"${val%%[![:space:]]*}"}"
  val="${val%"${val##*[![:space:]]}"}"
  [[ -z "${key:-}" || "$key" == \#* ]] && continue
  [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || { log "⚠️  Ignorado: clave inválida '$key'"; continue; }
  export "$key=$val"
done < "$ENV_FILE"

# Permite pinchar un tag desde CLI para interpolar en compose (p. ej. image: repo/app:${IMAGE_TAG})
if [[ -n "$IMAGE_TAG_ARG" ]]; then
  export IMAGE_TAG="$IMAGE_TAG_ARG"
  log "🏷️  IMAGE_TAG=$IMAGE_TAG"
fi

# ----------------------------
# 2) Comprobaciones previas
# ----------------------------
if [[ ! -f "$CONFIG_FILE" ]]; then
  die "No se encontró $CONFIG_FILE. Asegúrate de tener tu olts.yaml ahí."
fi

# Mostrar interpolación para diagnosticar
log "🧾 Compose efectivo (variables interpoladas):"
docker compose "${COMPOSE_FILES[@]}" config >/dev/null || die "Fallo al generar 'compose config'"
docker compose "${COMPOSE_FILES[@]}" config --images | sed 's/^/  • /'

# ----------------------------
# 3) Reset opcional del stack
# ----------------------------
if [[ $DO_RESET -eq 1 ]]; then
  log "🧨 Bajando stack y eliminando volúmenes huérfanos… (down -v --remove-orphans)"
  docker compose "${COMPOSE_FILES[@]}" down -v --remove-orphans || true
fi

# ----------------------------
# 4) Pull opcional
# ----------------------------
if [[ $DO_PULL -eq 1 ]]; then
  log "🚀 Pull de imágenes…"
  docker compose "${COMPOSE_FILES[@]}" pull
else
  log "⏭️  Saltando 'pull' por petición (-P/--no-pull)"
fi

# ----------------------------
# 5) Build opcional
# ----------------------------
if [[ $DO_BUILD -eq 1 ]]; then
  log "🏗️  Reconstruyendo imágenes sin caché…"
  docker compose "${COMPOSE_FILES[@]}" build --no-cache
fi

# ----------------------------
# 6) Despliegue
# ----------------------------
log "🔨 Arrancando servicios (up -d --force-recreate --remove-orphans)…"
docker compose "${COMPOSE_FILES[@]}" up -d --force-recreate --remove-orphans

# ----------------------------
# 7) Estado + imágenes en uso
# ----------------------------
log "⏳ Esperando inicialización…"
sleep 10
log "✅ Estado de los servicios:"
docker compose "${COMPOSE_FILES[@]}" ps
log "🖼️  Imágenes en uso:"
docker compose "${COMPOSE_FILES[@]}" images | sed 's/^/  • /'

# ----------------------------
# 8) Logs (opcional) y guardado
# ----------------------------
if [[ $DO_LOGS -eq 1 ]]; then
  TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
  LOG_DIR="logs/${TIMESTAMP}"
  mkdir -p "$LOG_DIR"
  log "📥 Volcando logs en ${LOG_DIR}/"
  # Ajusta la lista de servicios a tus necesidades
  for svc in collector api; do
    if docker compose "${COMPOSE_FILES[@]}" ps --services | grep -q "^${svc}$"; then
      docker compose "${COMPOSE_FILES[@]}" logs --no-color "$svc" > "${LOG_DIR}/${svc}.log" || true
      log "   • ${svc}.log"
    fi
  done
fi

# ----------------------------
# 9) Limpieza de imágenes dangling
# ----------------------------
log "🧹 Limpiando imágenes dangling…"
docker image prune -f >/dev/null || true

log ""
log "🎉 Despliegue completado."
[[ $DO_LOGS -eq 1 ]] && log "🗂️  Logs guardados. Repite con -L cuando quieras."
