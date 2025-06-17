## Guía de desarrollo y pruebas



### 1 . Requisitos previos

| Herramienta     | Versión mínima          | Notas                                      |
| --------------- | ----------------------- | ------------------------------------------ |
| Docker Engine   | 24 .x                   | Linux o Docker Desktop (Win/Mac)           |
| Docker Compose  | integrado en Docker CLI | (`docker compose …`)                       |
| Python          | 3.12 (opcional)         | Sólo si quieres ejecutar los tests en host |
| Make (opcional) | 4.x                     | facilita comandos (`make up`)              |

---

### 2 . Clona y arranca en modo **desarrollo**

```bash
# ① descomprime el zip
unzip orchestrator-starter.zip -d olt-orchestrator
cd olt-orchestrator

# ② copia variables
cp .env.example .env           # edita contraseñas y DSN si lo deseas

# ③ crea un override para “hot-reloading”
cat > docker-compose.override.yml <<'EOF'
services:
  api:
    volumes:
      - ./api:/app/api        # monta tu código
    command: >
      uvicorn app.main:app
      --host 0.0.0.0 --port 8000 --reload

  collector:
    volumes:
      - ./collector:/app      # monta tu código
    command: >
      watchmedo auto-restart
      --directory=/app
      --pattern=*.py
      -- celery -A tasks worker -B --loglevel=info
EOF
# watchmedo viene con 'watchdog'; añade 'watchdog' a requirements si lo necesitas

# ④ arranca todo
docker compose up -d --build
```

*Ahora cualquier cambio en `api/` se recarga al instante en FastAPI y los workers Celery se reinician automáticamente cuando editas `collector/`.*

---

### 3 . Base de datos: migraciones y datos de prueba

1. **Conéctate** al contenedor:

   ```bash
   docker compose exec db psql -U postgres -d olt
   ```

2. Genera tablas iniciales (si no existen):

   ```sql
   \i api/app/sql/schema.sql   -- o usa Alembic más adelante
   ```

3. Semilla mínima para probar:

   ```sql
   INSERT INTO olt(vendor,host,port,username,password,description)
   VALUES ('huawei','192.0.2.10',23,'root','***','Lab OLT');
   ```

---

### 4 . Pruebas unitarias y de integración

#### a) Estructura recomendada

```
/tests
├── api           # tests de endpoints
│   └── test_geo.py
├── collector     # tests de lógica Celery / parsing
│   └── test_parse_huawei.py
└── conftest.py   # fixtures (db temp, client, etc.)
```

#### b) Ejecutar tests **en host** (rápido)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r api/requirements.txt -r collector/requirements.txt pytest httpx[cli] pytest-asyncio
pytest -q
```

Las pruebas usan `httpx.AsyncClient` para hacer peticiones al contenedor `api`:

```python
@pytest.mark.asyncio
async def test_geo_endpoint():
    async with AsyncClient(base_url="http://localhost:8000") as client:
        r = await client.get("/geo?bbox=-180,-90,180,90")
        assert r.status_code == 200
```

> Si prefieres tests **dentro** de Docker, añade un servicio `test` en `docker-compose.test.yml` con la misma imagen de `api` y monta `./tests`.

---

### 5 . Depuración

| Zona           | Cómo depurar                                                         |
| -------------- | -------------------------------------------------------------------- |
| **API**        | `docker compose logs -f api` o bien `curl -s localhost:8000/health`  |
| **Celery**     | `docker compose logs -f collector` *(tareas cada 5 min por defecto)* |
| **DB**         | `docker compose exec db psql …` + `SELECT …`                         |
| **Leaflet UI** | Navegador → `http://localhost` y usa DevTools / red                  |

*Tip:* en `app/main.py` puedes `import logging; logging.basicConfig(level=logging.DEBUG)` para trazas verborosas.

---

### 6 . Pruebas de extremo a extremo (E2E)

1. **Levanta Postman / Insomnia** y genera una colección:

   * `GET http://localhost:8000/geo?bbox=…`
   * `PUT http://localhost:8000/onts/1/position`
2. **Cypress** para la SPA Leaflet: añade un contenedor `cypress-run` que dispara pruebas UI.

---

### 7 . Workflow típico

| Paso                | Comando                                                                   |
| ------------------- | ------------------------------------------------------------------------- |
| Levantar todo       | `docker compose up -d --build`                                            |
| Ver logs live       | `docker compose logs -f api collector`                                    |
| Añadir una librería | edita `api/requirements.txt` → `docker compose up -d --build api`         |
| Ejecutar tests      | `pytest -q` (host) o `docker compose -f docker-compose.test.yml run test` |
| Parar entorno       | `docker compose down`                                                     |

---

### 8 . Próximos escalones

1. **Alembic** para migraciones versionadas (`alembic init migrations`).
2. **GitHub Actions**:

   * job “test” → `docker compose -f … up -d`, `pytest`, `docker compose down`.
3. **K6 o Locust** para carga del endpoint `/geo`.
4. **Prometheus & Grafana**: exportadores de Postgres y Celery.

---

Con estos pasos tienes un ciclo **código → hot-reload → tests → debug** completamente dentro de Docker, evitando “works on my machine”. Si necesitas templates de *fixtures*, ejemplos de parsing de las librerías Huawei/Zyxel o cómo integrar Alembic, dímelo y lo ampliamos. ¡A programar!
