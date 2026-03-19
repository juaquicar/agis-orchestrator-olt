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

### 0. Instalar dependencias

En `Ubuntu Server 24.04` instalar:

```bash
sudo snap install docker
git clone https://github.com/juaquicar/agis-orchestrator-olt.git
cd agis-orchestrator-olt
```

Comprueba también que tienes acceso Telnet/SSH a las OLTs que se van a configurar.

### 1. Variables de entorno: `.env` / `.env.prod`

En la raíz del proyecto crea un fichero `.env.prod` (o `.env` si no existe) con el siguiente contenido:

```dotenv
# ────────────────────────────
# PostgreSQL / TimescaleDB
# ────────────────────────────
POSTGRES_PASSWORD=changeme     # contraseña del super-usuario postgres
POSTGRES_DB=olt                # nombre de la base de datos que usará el servicio

# Cadena DSN que utilizan la API y el collector
DB_DSN=postgresql://postgres:changeme@db:5432/olt

# ────────────────────────────
# Redis  (broker Celery)
# ────────────────────────────
REDIS_URL=redis://redis:6379/0  # contenedor “redis” declarado en docker-compose, cuidado debe ser 6379, pero lo tengo ya en mi maq

# ────────────────────────────
# Seguridad API  (JWT)
# ────────────────────────────
JWT_SECRET=supersecret


# ────────────────────────────
# OLTs
# ────────────────────────────
OLT_CONFIG_PATH='/config/olts.yaml'
DELETE_ONTS=true


# ────────────────────────────
# aGIS CTOs
# ────────────────────────────
aGIS_HOST=https://agis-eu.stratosgs.com
aGIS_USER=USER
aGIS_PASS=PASS
aGIS_SERVICE=UUID_SERVICE


# ────────────────────────────
# NGINX
# ────────────────────────────
NGINX_FILE_PATH=./nginx.conf

```

> **Nota:** el script de despliegue buscará `.env.prod`; si no existe, usará `.env`.

### 2. Configuración de OLTs: `collector/config/olts.yaml`

Define tus equipos OLT en formato YAML. Ejemplo:

```yaml
# config/olts.yaml   (ejemplo completo)  
defaults:  
  poll_interval: 300            # 5 min  
  prompt: ">"                   # valor genérico; cada OLT puede sobre-escribirlo  
  
olts:  
  
  
  - id: huawei-TEST  
    vendor: huawei  
    host: 192.168.88.25  
    port: 23  
    username: root  
    password: admin  
    prompt: "MA5603T"  
    snmp_ip: 192.168.88.25  
    snmp_port: 161  
    snmp_community: public  
    description: "Huawei – Laboratorio"  
    poll_interval: 90  
    pon_list:  
      - frame: "0"  
        slot: 0  
        port: 0  
      - frame: "0"
        slot: 0
        port: 1
  
  - id: zyxel1408-TEST  
    vendor: zyxel1408A  
    host: 192.168.88.25  
    port: 23  
    username: admin  
    password: 1234  
    prompt: "OLT1408A#"  
    description: "Zyxel – TEST"  
    poll_interval: 20  
  
  - id: zyxel1240XA-TEST  
    vendor: zyxel1240XA  
    host: 192.168.88.25  
    port: 23  
    username: admin  
    password: 1234  
    prompt: "MSC1240XA#"  
    poll_interval: 300  
    description: "Zyxel 1240XA – TEST"  
    slots: ["1", "2", "4", "5", "6"]  
    timeout: 120  
  
  
  - id: zyxel2406-TEST  
    vendor: zyxel2406  
    host: 192.168.88.25  
    port: 23  
    username: admin  
    password: 1234 
    prompt: "OLT2406#"  
    description: "Zyxel 2406– TEST"  
    poll_interval: 300  
    debug: false  
    min_onts: 600  
    retry_once: true  
    timeout: 120
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
```

- **Redis** (volumen `redis_data`):
```bash
docker run --rm \
  -v redis_data:/data \
  -v "$env/backup:/backup" \
  alpine:3.18 \
  tar czvf /backup/redis_data_$(date +%F).tar.gz -C /data .
```

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


## Version 

- [22/01/26] v0.2.0
  - Integración de nuevas OLTs Zyxel 1240XA y 2406.
  - Optimización del sistema por índices geométricos, cachés de puertos PON, vistas materializadas...
  - Filtro de MAPA para no saturar vista y mejorar rendimientos. 
  - Fitrado en MAPA por OLT y PON.
  - Clasificación de ONTs sin ubicar por OLT y por PON. Árbol jerárquico.
  - Buscador de ONTs ubicadas y sin ubicar con zoom automática.
  - Exportación de ONTs a CSV.
  - Importación de ONTs con CSV con asociación a CTO y ubicación por coordenadas 4326 vía CSV.
  - Plugins de mapa para buscar en Nominatim, geolocalizador y centrador en ONTs.
  - Buscador de CTOs.
  - Mejora general de la interfaz. Look & Feel.
  - Renderizado de Serial y Descripción de las ONTs.
  - Mejora general del rendimiento de las APIs para aGIS.


## Autor

Juanma Quijada – juanma.quijada@stratosgs.com

## Licencia

MIT License – ver [LICENSE](LICENSE).

> Para más detalles técnicos, consulta la documentación interna o el repositorio en GitHub.
