from fastapi import APIRouter

from app.db import mongo

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    db_ok = await mongo.ping()
    return {"status": "ok" if db_ok else "degraded", "database": "ok" if db_ok else "unavailable"}
