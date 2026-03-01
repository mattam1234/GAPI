"""
Advanced search service with filtering, trending, and saved searches.
"""
import json
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_, desc, desc as sql_desc
from database import User_Library, SavedSearch, AuditLog


class SearchService:
    """Handles advanced game search and filtering."""

    def __init__(self, db_module, picker=None):
        self._db = db_module
        self._picker = picker

    def search_games(self, db, query: str, filters: dict = None, user_id: str = None):
        """Search games with advanced filters."""
        try:
            results = []

            if not self._picker or not hasattr(self._picker, 'games'):
                return results

            # Get all games
            all_games = getattr(self._picker, 'games', [])

            # Filter by query (search in name and tags)
            if query and query.strip():
                q_lower = query.lower()
                search_results = [
                    g for g in all_games
                    if q_lower in g.get('name', '').lower() or
                    q_lower in g.get('tags', '').lower()
                ]
            else:
                search_results = all_games

            # Apply advanced filters
            if filters:
                search_results = self._apply_filters(search_results, filters)

            # Sort by relevance/popularity
            search_results.sort(
                key=lambda g: (
                    -self._get_game_score(db, g.get('app_id')),
                    g.get('name', '')
                )
            )

            # Log search (for trending)
            if user_id:
                self._log_search(db, user_id, query, len(search_results))

            return search_results[:100]  # Limit to 100 results
        except Exception:
            return []

    def save_search(self, db, username: str, search_name: str, query: str, filters: dict = None):
        """Save a search for quick access."""
        try:
            saved = SavedSearch(
                username=username,
                search_name=search_name,
                query=query,
                filters=json.dumps(filters) if filters else None,
            )
            db.add(saved)
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False

    def get_saved_searches(self, db, username: str):
        """Get user's saved searches."""
        try:
            searches = db.query(SavedSearch).filter(
                SavedSearch.username == username
            ).order_by(
                desc(SavedSearch.pinned),
                desc(SavedSearch.last_used_at)
            ).all()

            return [
                {
                    'id': s.id,
                    'name': s.search_name,
                    'query': s.query,
                    'filters': json.loads(s.filters) if s.filters else {},
                    'pinned': s.pinned,
                    'use_count': s.use_count,
                }
                for s in searches
            ]
        except Exception:
            return []

    def delete_saved_search(self, db, search_id: int):
        """Delete a saved search."""
        try:
            db.query(SavedSearch).filter(SavedSearch.id == search_id).delete()
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False

    def pin_search(self, db, search_id: int, pinned: bool):
        """Pin or unpin a saved search."""
        try:
            search = db.query(SavedSearch).filter(SavedSearch.id == search_id).first()
            if search:
                search.pinned = pinned
                db.commit()
                return True
            return False
        except Exception:
            db.rollback()
            return False

    def get_trending_searches(self, db, days: int = 7, limit: int = 10):
        """Get trending search queries."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            results = db.query(
                AuditLog.description,
                func.count(AuditLog.id).label('count')
            ).filter(
                and_(
                    AuditLog.action == 'search',
                    AuditLog.timestamp >= cutoff,
                )
            ).group_by(AuditLog.description).order_by(
                func.count(AuditLog.id).desc()
            ).limit(limit).all()

            return [
                {'query': r[0], 'count': r[1]}
                for r in results if r[0]
            ]
        except Exception:
            return []

    def get_search_suggestions(self, db, query_prefix: str, limit: int = 5):
        """Get search suggestions based on prefix."""
        try:
            recent = db.query(SavedSearch.query).filter(
                SavedSearch.query.ilike(f'{query_prefix}%')
            ).distinct().limit(limit).all()

            return [r[0] for r in recent]
        except Exception:
            return []

    def log_search_history(self, db, username: str, query: str):
        """Log search for history/analytics."""
        try:
            self._log_search(db, username, query, 0)
        except Exception:
            pass

    # Private helpers

    def _apply_filters(self, games, filters):
        """Apply filters to game list."""
        result = games

        if filters.get('genres'):
            genres = [g.lower() for g in filters['genres']]
            result = [
                g for g in result
                if any(gen in g.get('genres', '').lower() for gen in genres)
            ]

        if filters.get('min_year'):
            min_year = int(filters['min_year'])
            result = [g for g in result if g.get('release_date', 2000) >= min_year]

        if filters.get('max_year'):
            max_year = int(filters['max_year'])
            result = [g for g in result if g.get('release_date', 2100) <= max_year]

        if filters.get('min_price'):
            min_price = float(filters['min_price'])
            result = [g for g in result if g.get('price', 0) >= min_price]

        if filters.get('max_price'):
            max_price = float(filters['max_price'])
            result = [g for g in result if g.get('price', 999) <= max_price]

        if filters.get('platforms'):
            platforms = filters['platforms']
            result = [g for g in result if g.get('platform') in platforms]

        if filters.get('exclude_tags'):
            exclude = [t.lower() for t in filters['exclude_tags']]
            result = [
                g for g in result
                if not any(t in g.get('tags', '').lower() for t in exclude)
            ]

        return result

    def _get_game_score(self, db, app_id):
        """Calculate a relevance score for a game."""
        try:
            # Score based on pick count + review count
            picks = db.query(AuditLog).filter(
                and_(
                    AuditLog.action == 'pick',
                    AuditLog.resource_id == str(app_id),
                )
            ).count()
            return picks
        except Exception:
            return 0

    def _log_search(self, db, username: str, query: str, result_count: int):
        """Log a search action."""
        try:
            from database import AuditLog
            log = AuditLog(
                username=username,
                action='search',
                description=query,
                resource_type='search',
                resource_id=None,
            )
            db.add(log)
            db.commit()
        except Exception:
            pass
