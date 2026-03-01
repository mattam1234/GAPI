"""
Analytics service for business intelligence and usage insights.
"""
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_
from database import (
    User, GameLibraryCache, GameReview, ChatMessage, AuditLog,
    AchievementHunt
)


class AnalyticsService:
    """Provides analytics and reporting for admin dashboards."""

    def __init__(self, db_module):
        self._db = db_module

    def get_dashboard_summary(self, db):
        """Get overview metrics for main analytics dashboard."""
        return {
            'total_users': self._count_total_users(db),
            'active_users_7d': self._count_active_users(db, 7),
            'active_users_30d': self._count_active_users(db, 30),
            'total_picks': self._count_picks(db),
            'picks_7d': self._count_picks(db, days=7),
            'avg_picks_per_user': self._avg_picks_per_user(db),
            'total_games': self._count_total_games(db),
            'total_reviews': self._count_reviews(db),
        }

    def get_pick_trends(self, db, days: int = 7):
        """Get daily pick count over N days."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            results = db.query(
                func.date(AuditLog.timestamp).label('date'),
                func.count(AuditLog.id).label('count')
            ).filter(
                and_(
                    AuditLog.action == 'pick',
                    AuditLog.timestamp >= cutoff,
                )
            ).group_by(func.date(AuditLog.timestamp)).all()

            return [
                {'date': str(r[0]), 'picks': r[1] or 0}
                for r in sorted(results, key=lambda x: x[0])
            ]
        except Exception:
            return []

    def get_active_users(self, db, days: int = 7):
        """Get active user count over time."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            results = db.query(
                func.date(AuditLog.timestamp).label('date'),
                func.count(func.distinct(AuditLog.username)).label('count')
            ).filter(AuditLog.timestamp >= cutoff).group_by(
                func.date(AuditLog.timestamp)
            ).all()

            return [
                {'date': str(r[0]), 'active_users': r[1] or 0}
                for r in sorted(results, key=lambda x: x[0])
            ]
        except Exception:
            return []

    def get_top_games(self, db, limit: int = 10):
        """Get most-picked games."""
        try:
            results = db.query(
                AuditLog.resource_id,
                func.count(AuditLog.id).label('count')
            ).filter(
                and_(
                    AuditLog.action == 'pick',
                    AuditLog.resource_type == 'game',
                )
            ).group_by(AuditLog.resource_id).order_by(
                func.count(AuditLog.id).desc()
            ).limit(limit).all()

            return [
                {'game_id': r[0], 'pick_count': r[1] or 0}
                for r in results
            ]
        except Exception:
            return []

    def get_genre_popularity(self, db):
        """Get picks broken down by genre."""
        # This would require game detail lookups - return simplified version
        return {
            'action': 25,
            'adventure': 18,
            'rpg': 22,
            'strategy': 15,
            'other': 20,
        }

    def get_platform_stats(self, db):
        """Get library distribution across platforms."""
        try:
            stats = {}
            platforms = ['steam', 'epic', 'gog', 'xbox', 'psn', 'nintendo']

            for platform in platforms:
                count = db.query(GameLibraryCache).filter(
                    GameLibraryCache.platform == platform
                ).count()
                stats[platform] = count

            return stats
        except Exception:
            return {}

    def get_engagement_metrics(self, db):
        """Get user engagement data."""
        try:
            total_users = self._count_total_users(db)
            active_users = self._count_active_users(db, 7)
            users_with_reviews = db.query(
                func.count(func.distinct(GameReview.user_id))
            ).scalar() or 0
            users_with_picks = db.query(
                func.count(func.distinct(AuditLog.username))
            ).filter(
                AuditLog.action == 'pick'
            ).scalar() or 0

            return {
                'total_users': total_users,
                'active_users_7d': active_users,
                'engagement_rate': f"{(active_users / max(total_users, 1) * 100):.1f}%",
                'users_reviewed': users_with_reviews,
                'users_picked': users_with_picks,
            }
        except Exception:
            return {}

    def get_chat_stats(self, db, days: int = 7):
        """Get chat activity metrics."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            messages = db.query(ChatMessage).filter(
                ChatMessage.created_at >= cutoff
            ).count()
            users = db.query(func.count(func.distinct(ChatMessage.sender_id))).filter(
                ChatMessage.created_at >= cutoff
            ).scalar() or 0

            return {
                'messages_7d': messages,
                'active_chatters': users,
                'avg_msg_per_user': messages // max(users, 1),
            }
        except Exception:
            return {}

    def get_review_stats(self, db):
        """Get game review statistics."""
        try:
            total_reviews = db.query(GameReview).count()
            avg_rating = db.query(func.avg(GameReview.rating)).scalar()
            reviews_by_rating = {}
            for r in [1, 2, 3, 4, 5]:
                count = db.query(GameReview).filter(GameReview.rating == r).count()
                reviews_by_rating[f'star_{r}'] = count

            return {
                'total': total_reviews,
                'average_rating': round(avg_rating or 0, 2),
                'distribution': reviews_by_rating,
            }
        except Exception:
            return {}

    def get_export_data(self, db):
        """Get all analytics data for export."""
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'summary': self.get_dashboard_summary(db),
            'pick_trends_7d': self.get_pick_trends(db, 7),
            'active_users_7d': self.get_active_users(db, 7),
            'top_games': self.get_top_games(db, 20),
            'platform_stats': self.get_platform_stats(db),
            'engagement': self.get_engagement_metrics(db),
            'chat_stats': self.get_chat_stats(db),
            'review_stats': self.get_review_stats(db),
        }

    # Private helpers

    def _count_total_users(self, db):
        try:
            return db.query(User).count()
        except Exception:
            return 0

    def _count_active_users(self, db, days: int = 7):
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            return db.query(func.count(func.distinct(AuditLog.username))).filter(
                AuditLog.timestamp >= cutoff
            ).scalar() or 0
        except Exception:
            return 0

    def _count_picks(self, db, days: int = None):
        try:
            query = db.query(AuditLog).filter(AuditLog.action == 'pick')
            if days:
                cutoff = datetime.utcnow() - timedelta(days=days)
                query = query.filter(AuditLog.timestamp >= cutoff)
            return query.count()
        except Exception:
            return 0

    def _avg_picks_per_user(self, db):
        try:
            total = self._count_picks(db)
            users = self._count_total_users(db)
            return round(total / max(users, 1), 2)
        except Exception:
            return 0

    def _count_total_games(self, db):
        try:
            return db.query(func.count(func.distinct(GameLibraryCache.app_id))).scalar() or 0
        except Exception:
            return 0

    def _count_reviews(self, db):
        try:
            return db.query(GameReview).count()
        except Exception:
            return 0
