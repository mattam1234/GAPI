#!/usr/bin/env python3
"""
Real-time communication module for GAPI using WebSockets and Server-Sent Events (SSE).
Handles live updates for leaderboards, activity feeds, notifications, and trades.
"""

import json
import asyncio
from datetime import datetime
from typing import Dict, Set, Callable
from collections import defaultdict
import logging

logger = logging.getLogger('gapi.realtime')

# ============================================================================
# Server-Sent Events (SSE) Implementation - Simpler, works over HTTP
# ============================================================================

class SSEBroadcaster:
    """Manages SSE connections and broadcasts events to connected clients"""
    
    def __init__(self):
        self.subscribers: Dict[str, Set[Callable]] = defaultdict(set)
        self.user_connections: Dict[str, Set] = defaultdict(set)  # Track user connections
    
    def subscribe(self, channel: str, callback: Callable):
        """Subscribe to a channel (e.g., 'leaderboard', 'activity', user-specific)"""
        self.subscribers[channel].add(callback)
        logger.info(f"New subscriber to channel: {channel}")
    
    def unsubscribe(self, channel: str, callback: Callable):
        """Unsubscribe from a channel"""
        self.subscribers[channel].discard(callback)
        logger.info(f"Removed subscriber from channel: {channel}")
    
    def broadcast(self, channel: str, event: dict):
        """Broadcast event to all subscribers on a channel"""
        logger.debug(f"Broadcasting to {channel}: {event}")
        for callback in self.subscribers.get(channel, set()):
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Error in subscriber callback: {e}")
    
    def broadcast_to_user(self, username: str, event: dict):
        """Send event to specific user"""
        channel = f"user:{username}"
        self.broadcast(channel, event)
    
    def get_sse_message(self, event_type: str, data: dict) -> str:
        """Format message as SSE"""
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# Global broadcaster instance
broadcaster = SSEBroadcaster()


# ============================================================================
# Event Types & Broadcasting Functions
# ============================================================================

class RealtimeEvents:
    """Centralized event broadcasting for all real-time features"""
    
    @staticmethod
    def leaderboard_update(category: str, username: str, value: int, position: int):
        """Broadcast leaderboard change"""
        event = {
            'type': 'leaderboard_update',
            'timestamp': datetime.utcnow().isoformat(),
            'category': category,
            'username': username,
            'value': value,
            'position': position
        }
        broadcaster.broadcast('leaderboard', event)
        logger.info(f"Leaderboard update: {username} - {category}")
    
    @staticmethod
    def activity_update(username: str, action: str, game: str = None, icon: str = '📍'):
        """Broadcast activity feed update"""
        event = {
            'type': 'activity',
            'timestamp': datetime.utcnow().isoformat(),
            'user': username,
            'action': action,
            'game': game,
            'icon': icon
        }
        broadcaster.broadcast('activity', event)
        logger.info(f"Activity: {username} - {action}")
    
    @staticmethod
    def trade_notification(to_user: str, from_user: str, trade_id: int, offer: str):
        """Notify user of trade offer"""
        event = {
            'type': 'trade_notification',
            'timestamp': datetime.utcnow().isoformat(),
            'from_user': from_user,
            'trade_id': trade_id,
            'offer': offer
        }
        broadcaster.broadcast_to_user(to_user, event)
        logger.info(f"Trade notification: {to_user} from {from_user}")
    
    @staticmethod
    def team_notification(username: str, event_type: str, team_name: str, data: dict = None):
        """Notify user of team events (joined, created, match, etc)"""
        event = {
            'type': f'team_{event_type}',
            'timestamp': datetime.utcnow().isoformat(),
            'team_name': team_name,
            'data': data or {}
        }
        broadcaster.broadcast_to_user(username, event)
        logger.info(f"Team notification: {username} - {event_type} on {team_name}")
    
    @staticmethod
    def ranking_change(username: str, old_tier: str, new_tier: str, new_points: int):
        """Notify user of rank change"""
        event = {
            'type': 'rank_promotion' if new_tier > old_tier else 'rank_update',
            'timestamp': datetime.utcnow().isoformat(),
            'old_tier': old_tier,
            'new_tier': new_tier,
            'points': new_points
        }
        broadcaster.broadcast_to_user(username, event)
        broadcaster.broadcast('rankings', event)
        logger.info(f"Rank change: {username} - {old_tier} → {new_tier}")
    
    @staticmethod
    def achievement_unlock(username: str, achievement_name: str, tier: str, icon: str):
        """Notify user of achievement unlock"""
        event = {
            'type': 'achievement_unlocked',
            'timestamp': datetime.utcnow().isoformat(),
            'achievement': achievement_name,
            'tier': tier,
            'icon': icon
        }
        broadcaster.broadcast_to_user(username, event)
        broadcaster.broadcast('achievements', event)
        logger.info(f"Achievement: {username} unlocked {achievement_name}")
    
    @staticmethod
    def pick_result(session_id: str, game_name: str, winner_username: str = None):
        """Broadcast pick/voting result"""
        event = {
            'type': 'pick_result',
            'timestamp': datetime.utcnow().isoformat(),
            'session_id': session_id,
            'winning_game': game_name,
            'winner': winner_username
        }
        broadcaster.broadcast('sessions', event)
        logger.info(f"Pick result: {session_id} - {game_name}")
    
    @staticmethod
    def shop_purchase(username: str, item_name: str, item_type: str):
        """Broadcast shop purchase (for cosmetics display)"""
        event = {
            'type': 'shop_purchase',
            'timestamp': datetime.utcnow().isoformat(),
            'username': username,
            'item': item_name,
            'item_type': item_type
        }
        broadcaster.broadcast('shop', event)
        broadcaster.broadcast_to_user(username, event)
        logger.info(f"Purchase: {username} bought {item_name}")
    
    @staticmethod
    def stream_started(username: str, stream_title: str, stream_url: str):
        """Notify followers of stream start"""
        event = {
            'type': 'stream_started',
            'timestamp': datetime.utcnow().isoformat(),
            'streamer': username,
            'title': stream_title,
            'url': stream_url
        }
        broadcaster.broadcast('streams', event)
        broadcaster.broadcast_to_user(username, event)
        logger.info(f"Stream started: {username} - {stream_title}")
    
    @staticmethod
    def notification_received(username: str, notif_type: str, message: str):
        """Real-time notification"""
        event = {
            'type': 'notification',
            'timestamp': datetime.utcnow().isoformat(),
            'notif_type': notif_type,
            'message': message
        }
        broadcaster.broadcast_to_user(username, event)
        logger.info(f"Notification: {username} - {notif_type}")


# ============================================================================
# WebSocket Implementation (Alternative to SSE - for future upgrades)
# ============================================================================

class WebSocketManager:
    """Manages WebSocket connections for real-time bidirectional communication"""
    
    def __init__(self):
        self.connections: Dict[str, Set] = defaultdict(set)  # username -> set of connections
        self.global_connections: Set = set()  # Global broadcast connections
    
    def register_user(self, username: str, connection_id):
        """Register a new connection for a user"""
        self.connections[username].add(connection_id)
        logger.info(f"WebSocket registered: {username}")
    
    def unregister_user(self, username: str, connection_id):
        """Unregister a connection"""
        self.connections[username].discard(connection_id)
        if not self.connections[username]:
            del self.connections[username]
        logger.info(f"WebSocket unregistered: {username}")
    
    def register_global(self, connection_id):
        """Register for global broadcasts"""
        self.global_connections.add(connection_id)
        logger.info(f"Global WebSocket registered")
    
    def get_user_connection_count(self, username: str) -> int:
        """Get number of active connections for user"""
        return len(self.connections.get(username, set()))
    
    def is_user_online(self, username: str) -> bool:
        """Check if user has active connections"""
        return username in self.connections and len(self.connections[username]) > 0


# Global WebSocket manager instance
ws_manager = WebSocketManager()


# ============================================================================
# Polling Fallback for Absence of WebSocket
# ============================================================================

class PollingCache:
    """Caches recent events for clients polling instead of using WebSocket/SSE"""
    
    def __init__(self, max_events: int = 100):
        self.events: Dict[str, list] = defaultdict(list)
        self.max_events = max_events
    
    def add_event(self, channel: str, event: dict):
        """Add event to cache"""
        event['cached_at'] = datetime.utcnow().isoformat()
        self.events[channel].append(event)
        
        # Keep only latest N events
        if len(self.events[channel]) > self.max_events:
            self.events[channel] = self.events[channel][-self.max_events:]
    
    def get_events_since(self, channel: str, timestamp: str) -> list:
        """Get events since a specific timestamp"""
        try:
            since = datetime.fromisoformat(timestamp)
            return [
                e for e in self.events.get(channel, [])
                if datetime.fromisoformat(e['cached_at']) > since
            ]
        except:
            return self.events.get(channel, [])[-10:]  # Last 10 if parsing fails
    
    def clear_old_events(self, max_age_seconds: int = 3600):
        """Clean up old events"""
        cutoff = datetime.utcnow().timestamp() - max_age_seconds
        for channel in self.events:
            self.events[channel] = [
                e for e in self.events[channel]
                if datetime.fromisoformat(e['cached_at']).timestamp() > cutoff
            ]


# Global polling cache
polling_cache = PollingCache()


# ============================================================================
# Setup for Flask/Quart Integration
# ============================================================================

def setup_realtime_routes(app):
    """
    Add real-time routes to Flask app.
    Call this in gapi_gui.py after creating the app.
    
    Usage:
        from realtime import setup_realtime_routes
        setup_realtime_routes(app)
    """
    from flask import Response, request
    from functools import wraps
    
    def require_login(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get username from session or auth header
            username = request.headers.get('X-Username')
            if not username:
                return {'error': 'Unauthorized'}, 401
            return f(username, *args, **kwargs)
        return decorated_function
    
    @app.route('/api/events/stream')
    @require_login
    def events_stream(username):
        """
        Server-Sent Events endpoint for real-time updates.
        
        Usage in JavaScript:
            const source = new EventSource('/api/events/stream');
            source.addEventListener('leaderboard_update', (e) => {
                const data = JSON.parse(e.data);
                console.log('Leaderboard:', data);
            });
        """
        def generate_events():
            # Send connection confirmation
            yield f"data: {json.dumps({'type': 'connected', 'username': username})}\n\n"
            
            # This would normally use a queue or connection pool
            # For now, use polling cache approach
            while True:
                try:
                    # Send user-specific events
                    user_events = polling_cache.get_events_since(f'user:{username}', 
                                                                  request.headers.get('Last-Event-ID', ''))
                    for event in user_events:
                        event_type = event.pop('type', 'update')
                        yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
                    
                    # Send global events
                    global_events = polling_cache.get_events_since('global', 
                                                                    request.headers.get('Last-Event-ID', ''))
                    for event in global_events:
                        event_type = event.pop('type', 'update')
                        yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
                    
                    asyncio.sleep(1)  # Poll every second
                except GeneratorExit:
                    break
                except Exception as e:
                    logger.error(f"Error in SSE stream: {e}")
                    break
        
        return Response(
            generate_events(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive'
            }
        )
    
    @app.route('/api/events/poll')
    @app.route('/api/events/poll/<channel>')
    @require_login
    def events_poll(username, channel='all'):
        """
        Polling endpoint for real-time updates (fallback).
        Clients can poll this periodically for new events.
        
        Usage:
            GET /api/events/poll?since=2024-03-01T12:00:00
            GET /api/events/poll/leaderboard?since=2024-03-01T12:00:00
        """
        since = request.args.get('since', '')
        
        channels = [channel] if channel != 'all' else [
            'global', f'user:{username}', 'leaderboard', 'activity', 
            'rankings', 'achievements', 'sessions', 'shop', 'streams'
        ]
        
        all_events = []
        for ch in channels:
            all_events.extend(polling_cache.get_events_since(ch, since))
        
        return {
            'success': True,
            'channel': channel,
            'events': all_events,
            'timestamp': datetime.utcnow().isoformat()
        }
    
    @app.route('/api/events/status')
    @require_login
    def events_status(username):
        """Get real-time system status"""
        return {
            'user': username,
            'is_online': ws_manager.is_user_online(username),
            'connections': ws_manager.get_user_connection_count(username),
            'sse_available': True,
            'polling_available': True,
            'timestamp': datetime.utcnow().isoformat()
        }
    
    logger.info("Real-time routes configured")


# ============================================================================
# Database Integration Helpers
# ============================================================================

def trigger_leaderboard_broadcast(db, category: str):
    """Get top users in category and broadcast changes"""
    try:
        query = f"""
            SELECT u.username, COUNT(*) as value FROM users u
            JOIN picks p ON u.username = p.username
            WHERE p.won = TRUE
            GROUP BY u.username
            ORDER BY value DESC LIMIT 10
        """
        rows = db.execute(query).fetchall()
        for position, (username, value) in enumerate(rows, 1):
            RealtimeEvents.leaderboard_update(category, username, value, position)
    except Exception as e:
        logger.error(f"Error broadcasting leaderboard: {e}")


def trigger_activity_broadcast(db):
    """Get recent activity and broadcast"""
    try:
        query = """
            SELECT DISTINCT u.username, 'made a pick' as action 
            FROM users u
            JOIN picks p ON u.username = p.username
            ORDER BY p.created_at DESC LIMIT 5
        """
        rows = db.execute(query).fetchall()
        for username, action in rows:
            RealtimeEvents.activity_update(username, action)
    except Exception as e:
        logger.error(f"Error broadcasting activity: {e}")
