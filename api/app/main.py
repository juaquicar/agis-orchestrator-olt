
from fastapi import FastAPI, Depends
from .database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

app = FastAPI(title="OLT Orchestrator API")

@app.get("/health")
async def health():
    return {"status": "ok"}

# Placeholder endpoint examples
@app.get("/geo")
async def geo(bbox: str, db: AsyncSession = Depends(get_db)):
    # TODO: implement GeoJSON response
    return {"type": "FeatureCollection", "features": []}
