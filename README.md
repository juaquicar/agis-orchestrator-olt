# AGIS Orchestrator OLT – Guía de Producción

Este paquete contiene un **esqueleto mínimo** para levantar:

* **TimescaleDB + PostGIS** – almacenamiento de medidas PTX/PRX y geometrías
* **Redis** – broker de colas
* **Collector (Celery)** – lee Huawei/Zyxel OLTs y persiste datos
* **FastAPI** – expone API REST para ONTs/CTOs y endpoint GeoJSON
* **Nginx + Leaflet admin‑UI** – interfaz web para posicionar ONTs ↔ CTOs

> ⚡  Listo para `docker compose up -d` y empezar a desarrollar.

## Estructura

```
.
├── docker-compose.yml
├── .env.example
├── nginx.conf
├── api/          # servicio FastAPI
├── collector/    # workers Celery
└── admin-ui/     # app Leaflet  Reemplaza valores en `.env` (copiar de `.env.example`) y ajusta `OLT_*` según tu red.
```

## 📦 Descripción General

AGIS Orchestrator OLT es un sistema que:

* Lee el estado de varias OLTs (Huawei MA56XXT, Zyxel OLT1408A…) y mide potencias (PTX/PRX) de ONTs.
* Almacena datos en PostgreSQL con TimescaleDB y PostGIS para series temporales y geolocalización.
* Expone una API REST para que aGIS TELCO consuma métricas y topología.
* Ofrece una interfaz web (Docker) que muestra un mapa interactivo con ONTs y CTOs.

---

## 🛠️ Prerrequisitos

* **Docker** v20.10+ y **Docker Compose** plugin (CLI `docker compose`).
* Acceso a un **registro de imágenes** (Docker Hub, Harbor…) con las imágenes `api`, `collector`, `nginx`, etc.
* Credenciales de **aGIS** (host, usuario, contraseña y service UUID).
* Fichero de configuración de OLTs en `collector/config/olts.yaml`.

```bash
tree collector/config
collector/config
└── olts.yaml
```

---

## ⚙️ Configuración

### 1. Variables de entorno: `.env` / `.env.prod`

En la raíz del proyecto crea un fichero `.env.prod` (o `.env` si no existe) con el siguiente contenido:

```dotenv
# PostgreSQL / TimescaleDB
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<tu_password>
POSTGRES_DB=olt
POSTGRES_HOST=db
POSTGRES_PORT=5432
# Si prefieres indicar directamente la URL de conexión:
# DB_DSN=postgresql://postgres:<tu_password>@db:5432/olt

# Redis (broker Celery)
REDIS_URL=redis://redis:6379/0

# Seguridad API (JWT)
JWT_SECRET=<clave_muy_segura>

# aGIS TELCO
aGIS_HOST=https://agis-eu.stratosgs.com
aGIS_USER=usuario.agis
aGIS_PASS=<tu_pass>
aGIS_SERVICE=<tu_service_uuid>
```

> **Nota:** el script de despliegue buscará `.env.prod`; si no existe, usará `.env`.

### 2. Configuración de OLTs: `collector/config/olts.yaml`

Define tus equipos OLT en formato YAML. Ejemplo:

```yaml
olts:
  - id: zyxel-central
    vendor: zyxel
    host: 192.168.1.10
    port: 22
    username: admin
    password: secret
    poll_interval: 300
    prompt: ">"
    description: Zyxel OLT central oficina

  - id: huawei-branch
    vendor: huawei
    host: 192.168.2.20
    port: 22
    username: root
    password: rootpass
    poll_interval: 300
    prompt: "OLT>"
    description: OLT sucursal Noroeste
```

El contenedor monta `collector/config` en `/config` y lee `/config/olts.yaml`.

---

## 🚀 Despliegue en Producción

1. **Compose Files:** utiliza `docker-compose.yml` junto con `docker-compose.prod.yml`, donde este último monta `collector/config`.
2. **Ejecuta el script de despliegue:**

   ```bash
   chmod +x deploy.prod.sh
   ./deploy.prod.sh
   ```

   * Hace `docker compose pull` de las imágenes.
   * Arranca los servicios con `--force-recreate --remove-orphans`.
   * Genera logs timestamped en `logs/YYYYMMDD_HHMMSS/collector.log` y `api.log`.

---

## 🛑 Apagado Seguro y Backup de Volúmenes

### 1. Parar servicios

```bash
docker compose down
```

### 2. Backup manual de volúmenes

* **PostgreSQL** (volumen `olt_data`):

```bash
docker run --rm -v olt_data:/var/lib/postgresql/data -v "$(pwd)/backup:/backup" alpine:3.18 sh -c "tar czf /backup/db-$(date +%F).tgz -C /var/lib/postgresql/data ."
````

- **Redis** (volumen `redis_data`):
```bash
docker run --rm \
  -v redis_data:/data \
  -v "$env/backup:/backup" \
  alpine:3.18 \
  tar czvf /backup/redis_data_$(date +%F).tar.gz -C /data .
````

* **Configuración & Logs**:

  ```bash
  cp -r collector/config "$env/backup/olts_config_$(date +%F)"
  cp -r logs "$env/backup/logs_$(date +%F)"
  ```

### 3. Restauración de volúmenes

Extrae el backup en el volumen correspondiente:

```bash
docker run --rm -v olt_data:/var/lib/postgresql/data -v "$(pwd)/backup:/backup" alpine:3.18 sh -c "rm -rf /var/lib/postgresql/data/* && tar xzf /backup/db-2025-06-24.tgz -C /var/lib/postgresql/data"
```

Repite para `redis_data` cambiando rutas.

---

## 🔍 Monitoreo y Mantenimiento

* **Ver logs en tiempo real:**

  ```bash
  docker compose logs -f collector api
  ```

* **Consultar estado de servicios:**

  ```bash
  docker compose ps
  ```

* **Limpiar imágenes dangling:**

  ```bash
  docker image prune -f
  ```

---


## Autor

Juanma Quijada – juanma.quijada@stratosgs.com

## Licencia

MIT License – ver [LICENSE](LICENSE).

> Para más detalles técnicos, consulta la documentación interna o el repositorio en GitHub.
