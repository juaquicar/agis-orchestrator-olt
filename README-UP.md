Aquí tienes una versión simplificada en dos ficheros:

```yaml
# docker-compose.yml (base, para producción)
version: "3.9"

services:
  db:
    image: timescale/timescaledb-ha:pg16
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - dbdata:/var/lib/postgresql/data
      - ./db-init:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres"]
      interval: 10s
      retries: 5
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    # en prod no exponemos puerto al host
    ports: []

  api:
    build: ./api
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    ports:
      - "8000:8000"
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
    environment:
      LOG_LEVEL: info

  collector:
    build: ./collector
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    command: celery -A tasks worker --loglevel=info --concurrency=4

  nginx:
    image: nginx:1.27-alpine
    volumes:
      - ./admin-ui:/usr/share/nginx/html:ro
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - api
    ports:
      - "80:80"

volumes:
  dbdata:
```

## ¿Cómo disparar uno u otro?

* **Desarrollo** (carga automática del `override`):

  ```bash
  docker-compose up --build
  ```

  > Docker Compose, al no recibir `-f`, buscará `docker-compose.yml` **y** `docker-compose.override.yml` automáticamente.

* **Producción** (sólo el fichero base):

  ```bash
  docker-compose --profile production up --build

  ```

  > Al especificar explícitamente `-f docker-compose.yml`, **no** se incluirá el `override`.

---

~~Con este esquema:

* El fichero **base** (`docker-compose.yml`) contiene la configuración común y la optimizada para producción.
* El **override** añade todo lo específico de desarrollo (montajes de código, recarga, puertos alternativos).
* Para desarrollo, basta con `docker-compose up`; para producción, indicamos sólo el base con `-f`.~~
