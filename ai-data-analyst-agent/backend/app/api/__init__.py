from fastapi import APIRouter

from app.api import ai, analytics, ask, auth, dashboard, datasets, exports, health, reports, share, sql

router = APIRouter()
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(dashboard.router)
router.include_router(ai.router)
router.include_router(datasets.router)
router.include_router(analytics.router)
router.include_router(sql.router)
router.include_router(exports.router)
router.include_router(reports.router)
router.include_router(ask.router)
router.include_router(share.router)
