FROM python:3.12-slim
WORKDIR /app

# --- dependencias del sistema necesarias para compilar y para git clone ---
RUN apt-get update \
 && apt-get install -y --no-install-recommends git build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["celery", "-A", "tasks", "worker", "-B", "--loglevel=info"]
