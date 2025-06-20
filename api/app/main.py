
# main.py (FastAPI)
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from .database import get_db  # helper para AsyncSession

app = FastAPI(
    title="OLT Orchestrator API",
    version="0.1.0",
)

# ───────────────────────── PING ────────────────────────────
@app.get("/health", tags=["misc"])
async def health() -> Dict[str, str]:
    return {"status": "ok"}

# ───────────────────────── GEOJSON ─────────────────────────
def parse_bbox(bbox: str) -> List[float]:
    try:
        minx, miny, maxx, maxy = map(float, bbox.split(","))
    except ValueError:
        raise HTTPException(400, "bbox debe ser 'minLon,minLat,maxLon,maxLat'")
    if minx >= maxx or miny >= maxy:
        raise HTTPException(400, "bbox inválido")
    return [minx, miny, maxx, maxy]

@app.get(
    "/geo",
    tags=["geo"],
    summary="Geometría de ONTs en BBOX",
    response_description="GeoJSON FeatureCollection"
)
async def geo(
    bbox: str = Query(
        ..., example="-3.80,40.38,-3.60,40.49",
        description="minLon,minLat,maxLon,maxLat"
    ),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    minx, miny, maxx, maxy = parse_bbox(bbox)
    sql = text("""
        SELECT
          o.id,
          o.olt_id,
          o.vendor_ont_id AS vendor_ont_id,
          o.serial,
          ST_AsGeoJSON(o.geom) AS geom
        FROM ont AS o
        WHERE 
            o.geom IS NOT NULL
            AND ST_Intersects(
            o.geom,
           ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)
        )
    """)
    result = await db.execute(sql, {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy})
    rows = result.fetchall()

    features: List[Dict[str, Any]] = []
    for r in rows:
        if r.geom:
            features.append({
                "type": "Feature",
                "geometry": json.loads(r.geom),
                "properties": {
                    "ont_id": r.id,
                    "olt_id": r.olt_id,
                    "vendor_ont_id": r.vendor_ont_id,
                    "serial": r.serial,
                },
            })
    return {"type": "FeatureCollection", "features": features}

# ──────────────────────── MODELOS API ───────────────────────
class Ont(BaseModel):
    id: int
    olt_id: str
    vendor_ont_id: str
    ptx: float | None = None
    prx: float | None = None
    status: str
    last_read: datetime = Field(..., description="Timestamp de la última lectura")
    props: Dict[str, Any] = Field(
        ..., description="Metadatos originales de la ONT (status, SN, modelo, …)"
    )

class OntList(BaseModel):
    total: int
    items: List[Ont]

class Point(BaseModel):
    time: datetime
    ptx: float | None = Field(None, example=-22.5)
    prx: float | None = Field(None, example=-26.8)
    status: str | None =  Field(None, example='online')

# ──────────────────── LISTADO DE ONTs ───────────────────────
@app.get(
    "/onts",
    response_model=OntList,
    tags=["onts"],
    summary="Listado de ONTs con última potencia, timestamp y props"
)
async def list_onts(
    limit: int = Query(20, le=1000),
    offset: int = 0,
    olt_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> OntList:
    where_clause = "WHERE o.olt_id = :olt" if olt_id else ""
    sql = text(f"""
        WITH last AS (
            SELECT DISTINCT ON (ont_id) ont_id, time, ptx, prx, status
              FROM ont_power
             ORDER BY ont_id, time DESC
        )
        SELECT
          o.id,
          o.olt_id,
          o.vendor_ont_id AS vendor_ont_id,
          o.status,
          l.ptx,
          l.prx,
          l.time   AS last_read,
          o.props
        FROM ont AS o
        JOIN last AS l ON l.ont_id = o.id
        {where_clause}
        ORDER BY o.id
        LIMIT :lim OFFSET :off
    """)
    result = await db.execute(sql, {"lim": limit, "off": offset, "olt": olt_id})
    rows = result.fetchall()

    items = [
        Ont(
            id=r.id,
            olt_id=r.olt_id,
            vendor_ont_id=r.vendor_ont_id,
            ptx=r.ptx,
            prx=r.prx,
            status=r.status,
            last_read=r.last_read,
            props=r.props,
        ) for r in rows
    ]
    total = await db.scalar(
        text("SELECT COUNT(*) FROM ont" + (" WHERE olt_id=:olt" if olt_id else "")),
        {"olt": olt_id}
    )
    return OntList(total=total or 0, items=items)

# ─────────────── SERIE TEMPORAL PTX/PRX ─────────────────────
@app.get(
    "/onts/{ont_id}/history",
    response_model=list[Point],
    tags=["onts"],
    summary="Serie de potencias de una ONT"
)
async def ont_history(
    ont_id: int,
    hours: int = Query(24, gt=0, le=24*30),
    db: AsyncSession = Depends(get_db),
) -> list[Point]:
    since = datetime.utcnow() - timedelta(hours=hours)
    sql = text("""
        SELECT time, ptx, prx, status
          FROM ont_power
         WHERE ont_id = :oid
           AND time >= :since
         ORDER BY time DESC
    """)
    result = await db.execute(sql, {"oid": ont_id, "since": since})
    rows = result.fetchall()
    if not rows:
        raise HTTPException(404, "ONT sin datos")
    return [Point(time=r.time, ptx=r.ptx, prx=r.prx, status=r.status) for r in rows]


# ─────────────── UBICAR Y UUID POR ADMIN-UI ─────────────────────
from fastapi import Path, Body

class OntPatch(BaseModel):
    cto_uuid: str | None = None
    lon: float | None = None
    lat: float | None = None

@app.patch("/onts/{ont_id}", tags=["onts"])
async def patch_ont(
    ont_id: int = Path(..., description="ID interno de la ONT"),
    patch: OntPatch = Body(...),
    db: AsyncSession = Depends(get_db),
):
    updates = []
    params = {"id": ont_id}
    if patch.cto_uuid is not None:
        updates.append("cto_uuid = :cto_uuid")
        params["cto_uuid"] = str(patch.cto_uuid)
        # al asociar CTO, podrías querer limpiar geom en ont:
        updates.append("geom = NULL")
    if patch.lon is not None and patch.lat is not None:
        updates.append("geom = ST_SetSRID(ST_Point(:lon, :lat),4326)")
        params["lon"] = patch.lon
        params["lat"] = patch.lat

    if not updates:
        raise HTTPException(400, "Nada que actualizar")

    sql = text(f"UPDATE ont SET {', '.join(updates)} WHERE id = :id")
    await db.execute(sql, params)
    await db.commit()
    return {"ok": True}