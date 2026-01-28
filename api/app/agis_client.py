import os
import httpx
from typing import List, Dict, Any

# Leer variables de entorno para conexión a AGIS
AGIS_HOST = os.getenv("aGIS_HOST")
AGIS_USER = os.getenv("aGIS_USER")
AGIS_PASS = os.getenv("aGIS_PASS")
AGIS_SERVICE = os.getenv("aGIS_SERVICE")

# Validación de configuración mínima
if not all([AGIS_HOST, AGIS_USER, AGIS_PASS, AGIS_SERVICE]):
    raise RuntimeError(
        "Error: Faltan variables de entorno AGIS_HOST, AGIS_USER, AGIS_PASS o AGIS_SERVICE"
    )

async def _get_agis_token() -> str:
    auth_url = f"{AGIS_HOST}/token-auth/login/"
    payload = {"username": AGIS_USER, "password": AGIS_PASS}
    print(f"[DEBUG] solicitando token a {auth_url}")
    async with httpx.AsyncClient() as client:
        resp = await client.post(auth_url, data=payload)
        print(f"[DEBUG] respuesta token status={resp.status_code}, body={resp.text}")
        resp.raise_for_status()
        token = resp.json().get("token")
        print(f"[DEBUG] token obtenido: {token}")
        if not token:
            raise RuntimeError(f"AGIS no devolvió token válido: {resp.text}")
        return token

async def fetch_cto_list() -> List[Dict[str, Any]]:
    """
    Consulta en AGIS la lista de CTOs (nombre y uuid).
    Devuelve una lista de diccionarios con keys: 'nombre' y 'uuid'.
    """
    token = await _get_agis_token()
    url = f"{AGIS_HOST}/api/v1/agis/SQLQuery/{AGIS_SERVICE}/"
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }
    body = {"query": "SELECT nombre, uuid from gen_equipos WHERE tipo=11"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "OK":
            raise RuntimeError(f"Error al obtener lista CTOs: {data}")
        return data.get("data", {}).get("rows", [])

async def fetch_cto_geojson() -> Dict[str, Any]:
    token = await _get_agis_token()
    url = f"{AGIS_HOST}/api/v1/agis/gis/GetGeoJSON/{AGIS_SERVICE}/gen_equipos/"
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }
    print(f"[DEBUG] GET GeoJSON a {url} con headers {headers}")
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        print(f"[DEBUG] respuesta GeoJSON status={resp.status_code}, body={resp.text[:200]}…")
        resp.raise_for_status()
        data = resp.json()
        print(f"[DEBUG] GeoJSON parseado: {list(data.keys())}")
        return data
