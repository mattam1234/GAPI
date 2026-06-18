"""Analytics domain — first vertical slice migrated to FastAPI.

Mirrors the legacy Flask routes:
  * GET /api/analytics/dashboard
  * GET /api/analytics/export

Both are admin-gated and reuse the existing ``AnalyticsService`` so there is a
single source of business-logic truth during the migration.
"""
from datetime import datetime

from fastapi import APIRouter, Depends

import gapi_gui
from app.services.analytics_service import AnalyticsService
from backend.dependencies import get_db, require_admin
from backend.schemas.analytics import AnalyticsDashboard

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def get_analytics_service() -> AnalyticsService:
    """Reuse the legacy singleton if present, else construct one."""
    return gapi_gui._analytics_service or AnalyticsService(gapi_gui.database)


@router.get("/dashboard", response_model=AnalyticsDashboard)
def analytics_dashboard(
    _admin: str = Depends(require_admin),
    db=Depends(get_db),
    svc: AnalyticsService = Depends(get_analytics_service),
) -> AnalyticsDashboard:
    """Admin analytics dashboard overview."""
    return AnalyticsDashboard(
        timestamp=datetime.utcnow().isoformat(),
        summary=svc.get_dashboard_summary(db),
        pick_trends_7d=svc.get_pick_trends(db, 7),
        active_users_7d=svc.get_active_users(db, 7),
        top_games=svc.get_top_games(db, 10),
        platform_stats=svc.get_platform_stats(db),
        engagement=svc.get_engagement_metrics(db),
        chat_stats=svc.get_chat_stats(db),
        review_stats=svc.get_review_stats(db),
    )


@router.get("/export", response_model=AnalyticsDashboard)
def analytics_export(
    _admin: str = Depends(require_admin),
    db=Depends(get_db),
    svc: AnalyticsService = Depends(get_analytics_service),
) -> AnalyticsDashboard:
    """Full analytics export (same shape, wider top-games window)."""
    data = svc.get_export_data(db)
    return AnalyticsDashboard(**data)
