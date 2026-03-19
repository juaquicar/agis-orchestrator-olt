import os
import httpx
import base64
import hashlib
import hmac
import secrets
import time
import urllib.parse
from typing import List, Dict, Any

# Leer variables de entorno para conexión a AGIS
AGIS_HOST = os.getenv("AGIS_HOST")
AGIS_SERVICE = os.getenv("AGIS_SERVICE")
AGIS_KEY_ID = os.getenv("AGIS_KEY_ID")
AGIS_SECRET = os.getenv("AGIS_SECRET")

# Validación de configuración mínima
if not all([AGIS_HOST, AGIS_SERVICE, AGIS_KEY_ID, AGIS_SECRET]):
    raise RuntimeError(
        "Error: Faltan variables de entorno AGIS_HOST, AGIS_SERVICE, AGIS_KEY_ID o AGIS_SECRET"
    )


# ─────────────────────────────────────────────────────────────
# HMAC helpers (mínimos)
# ─────────────────────────────────────────────────────────────
def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _canon_qs(params: dict) -> str:
    if not params:
        return ""
    items = []
    for k in sorted(params.keys()):
        v = params[k]
        if isinstance(v, (list, tuple)):
            for vv in sorted(map(str, v)):
                items.append((k, vv))
        else:
            items.append((k, str(v)))
    return urllib.parse.urlencode(items, quote_via=urllib.parse.quote)


def _sign(secret: str, canon: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), canon.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(mac).decode("utf-8")


def _build_headers(method: str, path: str, params: dict = None, body_bytes: bytes = b"") -> dict:
    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)
    body_hash = _sha256_hex(body_bytes or b"")

    canon = "\n".join([
        method.upper(),
        path,
        _canon_qs(params or {}),
        AGIS_KEY_ID,
        ts,
        nonce,
        body_hash,
    ])

    return {
        "X-Api-Key": AGIS_KEY_ID,
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "X-Content-SHA256": body_hash,
        "X-Signature": _sign(AGIS_SECRET, canon),
    }


# ─────────────────────────────────────────────────────────────
# Funciones originales (mínimamente tocadas)
# ─────────────────────────────────────────────────────────────

async def fetch_cto_list() -> List[Dict[str, Any]]:
    """
    Consulta en AGIS la lista de CTOs (nombre y uuid).
    Devuelve una lista de diccionarios con keys: 'nombre' y 'uuid'.
    """
    path = f"/api/v1/agis/SQLQuery/{AGIS_SERVICE}/"
    url = f"{AGIS_HOST}{path}"

    body = {"query": "SELECT nombre, uuid from gen_equipos WHERE tipo=11"}

    import json
    body_bytes = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    headers = _build_headers("POST", path, body_bytes=body_bytes)
    headers["Content-Type"] = "application/json"

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, content=body_bytes, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "OK":
            raise RuntimeError(f"Error al obtener lista CTOs: {data}")
        return data.get("data", {}).get("rows", [])


async def fetch_cto_geojson() -> Dict[str, Any]:
    path = f"/api/v1/agis/gis/GetGeoJSON/{AGIS_SERVICE}/gen_equipos/"
    url = f"{AGIS_HOST}{path}"

    headers = _build_headers("GET", path)

    print(f"[DEBUG] GET GeoJSON a {url} con headers {headers}")

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        print(f"[DEBUG] respuesta GeoJSON status={resp.status_code}, body={resp.text[:200]}…")
        resp.raise_for_status()
        data = resp.json()
        print(f"[DEBUG] GeoJSON parseado: {list(data.keys())}")

        if data.get("status") != "OK":
            raise RuntimeError(f"Error al obtener GeoJSON de CTOs: {data}")

        geojson = data.get("data")
        if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
            raise RuntimeError(f"AGIS devolvió un GeoJSON inválido: {data}")

        return geojson