from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from .database import get_db    # tu helper async_session

app = FastAPI(
    title="OLT Orchestrator API",
    version="0.1.0",
)

# ───────────────────────── PING ────────────────────────────
@app.get("/health", tags=["misc"])
async def health():
    return {"status": "ok ok"}


# ───────────────────────── GEOJSON ─────────────────────────
def parse_bbox(bbox: str) -> List[float]:
    try:
        minx, miny, maxx, maxy = map(float, bbox.split(","))
    except ValueError:
        raise HTTPException(400, "bbox debe ser 'minLon,minLat,maxLon,maxLat'")
    if minx >= maxx or miny >= maxy:
        raise HTTPException(400, "bbox inválido")
    return [minx, miny, maxx, maxy]


@app.get("/geo", tags=["geo"],
         summary="Geometría de ONTs en BBOX",
         response_description="GeoJSON FeatureCollection")
async def geo(
    bbox: str = Query(...,
                      example="-3.80,40.38,-3.60,40.49",
                      description="minLon,minLat,maxLon,maxLat"),
    db: AsyncSession = Depends(get_db),
):
    minx, miny, maxx, maxy = parse_bbox(bbox)

    sql = text("""
        SELECT ont.id, ont.olt_id, ont.serial,
               ST_AsGeoJSON(COALESCE(ont.geom, cto.geom)) AS geom
          FROM ont
          LEFT JOIN cto ON ont.cto_uuid = cto.uuid
         WHERE ST_Intersects(
                 COALESCE(ont.geom, cto.geom),
                 ST_MakeEnvelope(:minx,:miny,:maxx,:maxy,4326)
        )
    """)
    rows = (await db.execute(sql,
                             {"minx": minx, "miny": miny,
                              "maxx": maxx, "maxy": maxy})).fetchall()

    feats: List[Dict[str, Any]] = []
    for r in rows:
        if r.geom:
            feats.append({
                "type": "Feature",
                "geometry": json.loads(r.geom),
                "properties": {
                    "ont_id": r.id,
                    "olt_id": r.olt_id,
                    "serial": r.serial,
                },
            })
    return {"type": "FeatureCollection", "features": feats}


# ──────────────────────── MODELOS API ───────────────────────
class Ont(BaseModel):
    id: int
    olt_id: str
    ptx: float | None = None
    prx: float | None = None


class OntList(BaseModel):
    total: int
    items: List[Ont]


class Point(BaseModel):
    time: datetime
    ptx: float | None = Field(None, example=-22.5)
    prx: float | None = Field(None, example=-26.8)


# ──────────────────── LISTADO DE ONTs ───────────────────────
@app.get("/onts", response_model=OntList, tags=["onts"])
async def list_onts(
    limit: int = Query(20, le=1000),
    offset: int = 0,
    olt_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE o.olt_id = :olt" if olt_id else ""
    sql = text(f"""
        WITH last AS (
            SELECT DISTINCT ON (ont_id) ont_id, ptx, prx
              FROM ont_power
             ORDER BY ont_id, time DESC
        )
        SELECT o.id, o.olt_id, l.ptx, l.prx
          FROM ont AS o
          JOIN last AS l ON l.ont_id = o.id
          {where}
         ORDER BY o.id
         LIMIT :lim OFFSET :off
    """)
    rows = await db.execute(sql, {"lim": limit, "off": offset, "olt": olt_id})
    items = [Ont(id=r.id, olt_id=r.olt_id, ptx=r.ptx, prx=r.prx)
             for r in rows]

    total = await db.scalar(
        text("SELECT COUNT(*) FROM ont" + (" WHERE olt_id=:olt" if olt_id else "")),
        {"olt": olt_id},
    )
    return OntList(total=total, items=items)


# ─────────────── SERIE TEMPORAL PTX/PRX ─────────────────────
@app.get("/onts/{ont_id}/history",
         response_model=list[Point],
         tags=["onts"],
         summary="Serie de potencias de una ONT")
async def ont_history(
    ont_id: int,
    hours: int = Query(24, gt=0, le=24*30),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(hours=hours)
    sql = text("""
        SELECT time, ptx, prx
          FROM ont_power
         WHERE ont_id = :oid
           AND time >= :since
         ORDER BY time DESC
    """)
    rows = await db.execute(sql, {"oid": ont_id, "since": since})
    data = [Point(time=r.time, ptx=r.ptx, prx=r.prx) for r in rows]
    if not data:
        raise HTTPException(404, "ONT sin datos")
    return data
