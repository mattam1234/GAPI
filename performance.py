#!/usr/bin/env python3
"""
Performance & Caching Module for GAPI
Handles query optimization, caching, pagination, and response optimization
"""

import time
import hashlib
import json
from functools import wraps
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Callable
import logging

logger = logging.getLogger(__name__)


class CacheStore:
    """In-memory cache with TTL support and size limits"""
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        """
        Initialize cache store
        
        Args:
            max_size: Maximum number of cache entries
            default_ttl: Default time-to-live in seconds
        """
        self.store: Dict[str, Dict[str, Any]] = {}
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.hits = 0
        self.misses = 0
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set cache value with TTL"""
        if len(self.store) >= self.max_size:
            # Remove oldest entry
            oldest = min(self.store.items(), key=lambda x: x[1]['created_at'])
            del self.store[oldest[0]]
        
        self.store[key] = {
            'value': value,
            'created_at': time.time(),
            'ttl': ttl or self.default_ttl,
            'hits': 0
        }
    
    def get(self, key: str) -> Optional[Any]:
        """Get cache value if exists and not expired"""
        if key not in self.store:
            self.misses += 1
            return None
        
        entry = self.store[key]
        age = time.time() - entry['created_at']
        
        if age > entry['ttl']:
            del self.store[key]
            self.misses += 1
            return None
        
        entry['hits'] += 1
        self.hits += 1
        return entry['value']
    
    def invalidate(self, pattern: str) -> int:
        """Invalidate all keys matching pattern (glob-style)"""
        import fnmatch
        count = 0
        keys_to_delete = [k for k in self.store.keys() if fnmatch.fnmatch(k, pattern)]
        for key in keys_to_delete:
            del self.store[key]
            count += 1
        return count
    
    def clear(self) -> None:
        """Clear all cache"""
        self.store.clear()
        self.hits = 0
        self.misses = 0
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        return {
            'size': len(self.store),
            'max_size': self.max_size,
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': round(hit_rate, 2),
            'entries': len(self.store)
        }


# Global cache instance
_cache = CacheStore(max_size=2000, default_ttl=300)


def cached(ttl: int = 300, key_prefix: str = '') -> Callable:
    """
    Decorator for caching function results
    
    Args:
        ttl: Time-to-live in seconds
        key_prefix: Prefix for cache key
    
    Usage:
        @cached(ttl=600, key_prefix='user')
        def get_user_profile(user_id):
            return db.query(...)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from function name and arguments
            cache_key = f"{key_prefix}:{func.__name__}:{args}:{kwargs}"
            cache_key_hash = hashlib.md5(cache_key.encode()).hexdigest()
            
            # Try to get from cache
            cached_result = _cache.get(cache_key_hash)
            if cached_result is not None:
                logger.debug(f'Cache hit: {func.__name__}')
                return cached_result
            
            # Call function and cache result
            result = func(*args, **kwargs)
            _cache.set(cache_key_hash, result, ttl=ttl)
            logger.debug(f'Cache miss: {func.__name__} (cached for {ttl}s)')
            return result
        
        return wrapper
    return decorator


class Paginator:
    """Helper for pagination of query results"""
    
    @staticmethod
    def paginate(
        query_result: List[Any],
        page: int = 1,
        per_page: int = 20,
        total_count: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Paginate results
        
        Args:
            query_result: List of results
            page: Current page (1-indexed)
            per_page: Results per page
            total_count: Total count of all results (for pagination info)
        
        Returns:
            Dict with paginated data and metadata
        """
        if page < 1:
            page = 1
        
        total = total_count or len(query_result)
        total_pages = (total + per_page - 1) // per_page
        
        start = (page - 1) * per_page
        end = start + per_page
        
        items = query_result[start:end]
        
        return {
            'items': items,
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages,
            'has_prev': page > 1,
            'has_next': page < total_pages,
            'prev_page': page - 1 if page > 1 else None,
            'next_page': page + 1 if page < total_pages else None
        }
    
    @staticmethod
    def cursor_paginate(
        items: List[Dict],
        cursor: Optional[str] = None,
        limit: int = 20,
        cursor_field: str = 'id'
    ) -> Dict[str, Any]:
        """
        Cursor-based pagination (better for real-time data)
        
        Args:
            items: List of items with cursor field
            cursor: Base64-encoded position
            limit: Items to return
            cursor_field: Field to use as cursor
        
        Returns:
            Dict with items and next cursor
        """
        import base64
        
        # Decode cursor to find position
        position = 0
        if cursor:
            try:
                position = int(base64.b64decode(cursor).decode())
            except Exception:
                position = 0
        
        # Get items
        result_items = items[position:position + limit]
        
        # Create next cursor
        next_cursor = None
        if position + limit < len(items):
            next_cursor = base64.b64encode(str(position + limit).encode()).decode()
        
        return {
            'items': result_items,
            'cursor': cursor,
            'next_cursor': next_cursor,
            'has_more': bool(next_cursor),
            'count': len(result_items)
        }


class QueryOptimizer:
    """Database query optimization strategies"""
    
    @staticmethod
    def batch_select(db_session, model_class, ids: List[int]) -> Dict[int, Any]:
        """
        Batch select multiple items by ID (avoids N+1)
        
        Args:
            db_session: SQLAlchemy session
            model_class: Model class to query
            ids: List of IDs to fetch
        
        Returns:
            Dict mapping ID to model instance
        """
        if not ids:
            return {}
        
        results = db_session.query(model_class).filter(model_class.id.in_(ids)).all()
        return {result.id: result for result in results}
    
    @staticmethod
    def eager_load_relations(model) -> Any:
        """
        Calculate relationships to eager load for a model
        
        Returns:
            SQLAlchemy options for joinedload/selectinload
        """
        from sqlalchemy.orm import joinedload
        return model
    
    @staticmethod
    def count_distinct(db_session, model_class, field) -> int:
        """Count distinct values in a field"""
        from sqlalchemy import func
        result = db_session.query(func.count(func.distinct(field))).scalar()
        return result or 0


class ResponseOptimizer:
    """Optimize API responses"""
    
    @staticmethod
    def compress_json(data: Dict) -> str:
        """Compress JSON response"""
        return json.dumps(data, separators=(',', ':'), default=str)
    
    @staticmethod
    def partial_response(data: Dict, fields: List[str]) -> Dict:
        """Return only requested fields (sparse fieldsets)"""
        if not fields:
            return data
        
        if isinstance(data, list):
            return [ResponseOptimizer.partial_response(item, fields) for item in data]
        
        return {k: v for k, v in data.items() if k in fields}
    
    @staticmethod
    def add_etag(data: Dict) -> str:
        """Generate ETag for response caching"""
        json_str = ResponseOptimizer.compress_json(data)
        return hashlib.md5(json_str.encode()).hexdigest()


class IndexAnalyzer:
    """Suggest database indexes for performance"""
    
    @staticmethod
    def analyze_query_bottlenecks() -> List[str]:
        """
        Analyze common query patterns and suggest indexes
        This should be run periodically to identify slow queries
        """
        suggestions = [
            # User-related queries
            "CREATE INDEX idx_users_username ON users(username);",
            "CREATE INDEX idx_users_email ON users(email);",
            
            # Game-related queries
            "CREATE INDEX idx_games_steam_id ON games(steam_id);",
            "CREATE INDEX idx_games_appid ON games(appid);",
            
            # Activity tracking
            "CREATE INDEX idx_picks_username_created ON picks(username, created_at);",
            "CREATE INDEX idx_favorites_username ON favorites(username);",
            
            # Social features
            "CREATE INDEX idx_friends_user_id ON friendships(user_id);",
            "CREATE INDEX idx_follows_follower ON follows(follower_id);",
            
            # Leaderboards
            "CREATE INDEX idx_leaderboard_ranks_season_rank ON leaderboard_ranks(season, rank);",
            "CREATE INDEX idx_leaderboard_ranks_user_season ON leaderboard_ranks(user_id, season);",
            
            # Chat
            "CREATE INDEX idx_chat_messages_room_created ON chat_messages(chat_room, created_at);",
            
            # Phase 6 tables
            "CREATE INDEX idx_user_inventory_user ON user_inventory(user_id);",
            "CREATE INDEX idx_stream_vods_user ON stream_vods(user_id);",
            "CREATE INDEX idx_trade_offers_to_user ON trade_offers(to_user_id);",
            "CREATE INDEX idx_team_memberships_user ON team_memberships(user_id);",
            "CREATE INDEX idx_ranked_ratings_user ON ranked_ratings(user_id);",
            
            # Phase 7 tables
            "CREATE INDEX idx_battle_pass_users_active ON user_battle_passes(user_id, battle_pass_id);",
            "CREATE INDEX idx_tournament_participants_tournament ON tournament_participants(tournament_id);",
            "CREATE INDEX idx_guild_members_guild ON guild_members(guild_id);",
            "CREATE INDEX idx_trading_market_seller ON trading_markets(seller_id);",
            "CREATE INDEX idx_event_participation_user_event ON event_participations(user_id, event_id);",
        ]
        return suggestions


class PerformanceMonitor:
    """Monitor API performance metrics"""
    
    def __init__(self):
        self.metrics: Dict[str, List[float]] = {}
        self.start_times: Dict[str, float] = {}
    
    def start_timer(self, timer_name: str) -> None:
        """Start a performance timer"""
        self.start_times[timer_name] = time.time()
    
    def end_timer(self, timer_name: str) -> float:
        """End timer and record elapsed time"""
        if timer_name not in self.start_times:
            return 0
        
        elapsed = time.time() - self.start_times[timer_name]
        
        if timer_name not in self.metrics:
            self.metrics[timer_name] = []
        
        self.metrics[timer_name].append(elapsed)
        
        # Keep only last 100 measurements
        if len(self.metrics[timer_name]) > 100:
            self.metrics[timer_name] = self.metrics[timer_name][-100:]
        
        del self.start_times[timer_name]
        return elapsed
    
    def get_stats(self, timer_name: str) -> Dict[str, float]:
        """Get statistics for a timer"""
        if timer_name not in self.metrics or not self.metrics[timer_name]:
            return {}
        
        values = self.metrics[timer_name]
        return {
            'count': len(values),
            'min': round(min(values) * 1000, 2),  # Convert to ms
            'max': round(max(values) * 1000, 2),
            'avg': round(sum(values) / len(values) * 1000, 2),
            'total': round(sum(values) * 1000, 2)
        }
    
    def get_all_stats(self) -> Dict[str, Dict]:
        """Get stats for all timers"""
        return {name: self.get_stats(name) for name in self.metrics}


# Global performance monitor
_monitor = PerformanceMonitor()


def monitoring(endpoint_name: str) -> Callable:
    """
    Decorator for monitoring endpoint performance
    
    Usage:
        @app.route('/api/users')
        @monitoring('list_users')
        def list_users():
            return jsonify(...)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            _monitor.start_timer(endpoint_name)
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                elapsed = _monitor.end_timer(endpoint_name)
                logger.debug(f'{endpoint_name}: {elapsed * 1000:.2f}ms')
        
        return wrapper
    return decorator


class LazyLoadHelper:
    """Helper for lazy-loading UI data"""
    
    @staticmethod
    def create_lazy_load_url(endpoint: str, page: int = 1, per_page: int = 20) -> str:
        """Create URL for lazy-loading data"""
        return f"{endpoint}?page={page}&per_page={per_page}"
    
    @staticmethod
    def extract_pagination_params(request_args) -> Tuple[int, int]:
        """Extract pagination from request args"""
        page = int(request_args.get('page', 1))
        per_page = int(request_args.get('per_page', 20))
        
        # Enforce limits
        page = max(1, page)
        per_page = min(100, max(1, per_page))  # Max 100 per page
        
        return page, per_page


def get_cache() -> CacheStore:
    """Get global cache instance"""
    return _cache


def get_monitor() -> PerformanceMonitor:
    """Get global performance monitor"""
    return _monitor
