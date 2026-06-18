"""Response schemas for the analytics domain.

These mirror the shapes produced by ``app.services.analytics_service``. All
fields carry defaults so that the service's defensive ``except: return {}``
fallbacks still validate into a well-formed response.
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class DashboardSummary(BaseModel):
    total_users: int = 0
    active_users_7d: int = 0
    active_users_30d: int = 0
    total_picks: int = 0
    picks_7d: int = 0
    avg_picks_per_user: float = 0
    total_games: int = 0
    total_reviews: int = 0


class PickTrendPoint(BaseModel):
    date: str
    picks: int = 0


class ActiveUsersPoint(BaseModel):
    date: str
    active_users: int = 0


class TopGame(BaseModel):
    game_id: Optional[str] = None
    game_name: Optional[str] = None
    pick_count: int = 0


class EngagementMetrics(BaseModel):
    total_users: int = 0
    active_users_7d: int = 0
    engagement_rate: str = "0.0%"
    users_reviewed: int = 0
    users_picked: int = 0


class ChatStats(BaseModel):
    messages_7d: int = 0
    active_chatters: int = 0
    avg_msg_per_user: int = 0


class ReviewStats(BaseModel):
    total: int = 0
    average_rating: float = 0
    distribution: Dict[str, int] = Field(default_factory=dict)


class AnalyticsDashboard(BaseModel):
    """Payload for GET /api/analytics/dashboard and /api/analytics/export.

    Both legacy endpoints return the same shape; export simply widens the
    top-games limit.
    """
    timestamp: str
    summary: DashboardSummary
    pick_trends_7d: List[PickTrendPoint] = Field(default_factory=list)
    active_users_7d: List[ActiveUsersPoint] = Field(default_factory=list)
    top_games: List[TopGame] = Field(default_factory=list)
    platform_stats: Dict[str, int] = Field(default_factory=dict)
    engagement: EngagementMetrics = Field(default_factory=EngagementMetrics)
    chat_stats: ChatStats = Field(default_factory=ChatStats)
    review_stats: ReviewStats = Field(default_factory=ReviewStats)
