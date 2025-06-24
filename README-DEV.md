# README-DEV.md

Este documento está dirigido a desarrolladores que quieran trabajar, extender y probar el **OLT-Orchestrator** en modo desarrollo.

---


## Visión general

El **OLT-Orchestrator** es un sistema de orquestación y monitorización de OLTs/ONTs que:

* **Colecciona** datos de potencias (PTX/PRX) y estados de ONTs de múltiples OLTs (Huawei, Zyxel, etc.).
* **Almacena** la información en PostgreSQL con TimescaleDB (series temporales) y PostGIS (geoespacial).
* **Expone** una API REST (FastAPI) para consultar salud, geojson, listado de ONTs y series de potencias.
* **Admin-UI** en Docker con un mapa interactivo para ubicar ONTs y asociarlas a CTOs obtenidas de aGIS TELCO.

## Prerequisitos

* Docker & Docker Compose (>= v2)
* Python 3.12 (para tests locales)
* `make` (opcional)
* Acceso a Redis (por defecto en `redis://redis:6379/0`)
* Acceso a un servidor aGIS TELCO (solo en integración CTO)

## Estructura del repositorio

```
├── admin-ui/            # Frontend estático (HTML, CSS, JS)
├── api/                 # FastAPI + Pydantic + SQLAlchemy Async
├── collector/           # Celery worker + tareas de polling OLTs
├── db-init/             # Scripts SQL de extensiones y esquema
├── test/                # Tests y cliente API de ejemplo (api_client.py)
├── docker compose.yml   # Definición de servicios Docker
├── Dockerfile (api)     # Para la imagen de la API
├── deploy.dev.sh        # Script de despliegue local rápido
└── ...
```

## Variables de entorno

Crea un fichero `.env` (o copia el .env.example con tus variables).


## Arranque del entorno de desarrollo

1. Clona el repositorio:

```bash
git clone [https://github.com/juaquicar/agis-orchestrator-olt.git](https://github.com/juaquicar/agis-orchestrator-olt.git)
cd agis-orchestrator-olt
````

2. Lanza todos los servicios en segundo plano:
```bash
docker compose up -d --build
# o ./deploy.dev.sh para un alias rápido si queires sistemas de logs y demás. 
```



3. Verifica que los contenedores estén `Up`:

```bash
docker compose ps
````

4. Inicializa la base de datos (solo al primer arranque):
- Los scripts en `db-init/` se ejecutan automáticamente gracias a Docker y al directorio `docker-entrypoint-initdb.d`.

5. Accede:
- **API**: http://localhost:8000/docs (Swagger UI)
- **Admin-UI**: http://localhost:8888/


## Monitoreo de logs

Para depurar y seguir en tiempo real:

- Logs de todos los servicios:
```bash
docker compose logs -f
```

* Solo Collector (polling OLT):
```bash
docker compose logs -f collector
```

- Solo API (FastAPI):
```bash
docker compose logs -f api
```

* Solo Admin-UI (servidor estático/nginx):

```bash
docker compose logs -f nginx
```


## Apagar el entorno

```bash
docker compose down
# para eliminar volúmenes y datos:
docker compose down -v
```

## Base de datos y migraciones

* **Extensiones**: TimescaleDB & PostGIS (`01_extensions.sql`)fileciteturn0file1
* **Esquema inicial**: `02_schema.sql`
* **Props & status**: `20250618_add_props_and_last_read.sql`, `20250618_add_status.sql`

Para rehacer la BD en local:

```bash
docker compose down -v
docker compose up -d db
# espera a que termine, luego levanta el resto
docker compose up -d
```

## Testeo de la API

1. Instala dependencias de test:

```bash
pip install -r test/requirements.txt
```

2. Usar el cliente CLI de ejemplo (`test/api_client.py`):
```bash
cd test
python api_client.py health
gitpython api_client.py list --olt zyxel-central --limit 5
```

3. Con `curl` o Postman contra `http://localhost:8000`:

```bash
curl [http://localhost:8000/health](http://localhost:8000/health)
curl "[http://localhost:8000/onts?limit=10](http://localhost:8000/onts?limit=10)"
```

4. Ejecutar tests unitarios (añade más según vayas creando lógica):
```bash
pytest test/
```

## Arquitectura y modelos de datos

### Tablas principales (PostgreSQL + TimescaleDB + PostGIS)

| Tabla          | Descripción                                                                       |
| -------------- | --------------------------------------------------------------------------------- |
| **olt**        | Catálogo de OLTs (id, vendor, host, credenciales)                                 |
| **ont**        | ONTs detectadas (id interno, `vendor_ont_id`, geolocalización, `props`, `status`) |
| **ont\_power** | Serie de tiempo de potencias (`time`, `ptx`, `prx`, `status`)                     |

* `ont_power` es un **hypertable** (`time` como partición) para rendimiento en series largas.
* `ont.geom` usa `geometry(Point,4326)` para coord. WGS84 y permite filtros geográficos.
* `ont.props` almacena metadatos originales (`SN`, `Model`, `run_state`, etc.).

### Modelos Pydantic (API)

```python
class Ont(BaseModel):
    id: int
    olt_id: str
    vendor_ont_id: str
    ptx: Optional[float]
    prx: Optional[float]
    status: str
    cto_uuid: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    last_read: datetime
    props: Dict[str, Any]
```

```python
class Point(BaseModel):
    time: datetime
    ptx: Optional[float]
    prx: Optional[float]
    status: Optional[str]
```

Endpoints clave:

| Ruta                            | Método | Descripción                              |
| ------------------------------- | ------ | ---------------------------------------- |
| `/health`                       | GET    | Estado del servicio                      |
| `/geo?bbox=minx,miny,maxx,maxy` | GET    | GeoJSON de ONTs en un bounding box       |
| `/onts?limit=&offset=&olt_id=`  | GET    | Listado con última potencia y metadatos  |
| `/onts/{ont_id}/history?hours=` | GET    | Serie PTX/PRX de la ONT en horas previas |
| `/onts/{ont_id}`                | PATCH  | Actualizar `cto_uuid` o `lat`/`lon`      |
| `/ctos/list`                    | GET    | Lista de CTOs desde aGIS TELCO           |
| `/ctos/geojson`                 | GET    | GeoJSON de CTOs desde aGIS TELCO         |

## Integración de nuevas OLTs / fabricantes

Para añadir soporte de un nuevo fabricante u OLT desde cero, sigue estos pasos en el **collector**:

1. **Instalar la librería Python**

   * Asegúrate de que la librería de cliente de la OLT esté disponible en tu entorno (p.ej. `pip install jmq_olt_nuevo`).
   * Añade esta dependencia a `collector/requirements.txt`.

2. **Configurar `olts.yaml`**

   * Abre `collector/config/olts.yaml` y define tu nuevo vendor y la instancia de OLT:

   ```yaml
   defaults:
     poll_interval: 300
     port: 23
     prompt: "> "
   olts:
     - id: olt-nuevo-01
       vendor: nuevo
       host: 10.0.0.1
       port: 443        # puerto si no es Telnet
       username: admin
       password: secr3t
       poll_interval: 120    # override opcional
       prompt: "> "         # override opcional
       headers:
         User-Agent: "MyCustomClient/1.0"
         X-Auth-Token: "token123"
   ```

   * El bloque `headers` es opcional y se pasará al cliente si la librería lo soporta.

3. **Extender `collector/tasks.py`: `build_client`**

   * Localiza la función `build_client(cfg)` y añade un bloque `elif` para tu vendor:

   ```python
   def build_client(cfg):
       vendor = cfg['vendor']
       if vendor == 'huawei':
           from huawei_api import HuaweiClient
           return HuaweiClient(host=cfg['host'], port=cfg['port'], username=cfg['username'], password=cfg['password'])
       elif vendor == 'zyxel':
           from zyxel_api import ZyxelClient
           return ZyxelClient(host=cfg['host'], port=cfg['port'], username=cfg['username'], password=cfg['password'], prompt=cfg.get('prompt'))
       elif vendor == 'nuevo':
           from jmq_olt_nuevo import NuevoOLTClient
           # Pasar cabeceras HTTP si las define el usuario
           headers = cfg.get('headers', {})
           return NuevoOLTClient(
               host=cfg['host'],
               port=cfg['port'],
               username=cfg['username'],
               password=cfg['password'],
               prompt=cfg.get('prompt'),
               headers=headers
           )
       else:
           raise ValueError(f"Vendor '{vendor}' no soportado")
   ```

4. **Mapeo de datos en `poll_single_olt`**

   * Dentro de `tasks.py`, modifica o extiende el handler de polling para extraer de la respuesta de la librería los campos:

     * **vendor\_id** (ID interno de la ONT)
     * **ptx** y **prx** (potencias TX/RX)
     * **status** (estado operativo)
     * **props** (metadatos crudos)
   * Ejemplo simplificado:

   ```python
   def poll_single_olt(client, olt_cfg):
       raw_onts = client.list_onts()
       timestamp = datetime.utcnow()
       for raw in raw_onts:
           ont = {
               'vendor_ont_id': raw['id'],
               'ptx': raw.get('tx_power'),
               'prx': raw.get('rx_power'),
               'status': raw.get('status'),
               'props': raw
           }
           upsert_ont_power(olt_cfg['id'], ont, timestamp)
   ```

5. **Sincronizar catálogo de OLTs**

   * Cada vez que modifiques `olts.yaml`, sincroniza la tabla `olt`:

   ```bash
   docker compose exec collector python - << 'EOF'
   from tasks import sync_db
   sync_db()
   EOF
   ```

6. **Pruebas**

   * Añade tests en `test/api_client.py` simulando el nuevo cliente:

     ```python
     from jmq_olt_nuevo import NuevoOLTClient

     def test_list_onts_mock(monkeypatch):
         # simula respuesta
         monkeypatch.setattr(NuevoOLTClient, 'list_onts', lambda self: [{'id':'1','tx_power':1,'rx_power':-20,'status':'up'}])
         client = NuevoOLTClient(host='x',port=1,user='u',pass='p')
         assert len(client.list_onts()) == 1
     ```

---

## Admin-UI & Mapa interactivo & Mapa interactivo

* Ubicación: `admin-ui/index.html`, `admin-ui/css/style.css`, `admin-ui/js/{api.js,app.js}`
* Basado en **Leaflet** y **markerCluster** para visualizar ONTs y CTOs.
* Rutas base:

  * API (FastAPI) en `http://localhost:8000`
  * UI servir estático con **nginx** en `http://localhost:8888`

Actions principales:

* **Localizar ONT**: seleccionar ONT sin coords en lista lateral y click en mapa → PATCH `/onts/{id}` con `{ lat, lon }`.
* **Asignar/Desasignar CTO**: botón en popup → PATCH `/onts/{id}` con `{ cto_uuid }` o `null`.


---


## Autor

Juanma Quijada – juanma.quijada@stratosgs.com

## Licencia

MIT License – ver [LICENSE](LICENSE).

¡Bienvenido al desarrollo del OLT-Orchestrator! Cualquier duda o contribución es bienvenida. Estamos abiertos a sugerencias y mejoras.
