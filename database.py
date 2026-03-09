#!/usr/bin/env python3
"""
Database models and configuration for GAPI.
Handles PostgreSQL connections for user data, ignored games, and achievements.
"""

import os
import json
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Table, Float, UniqueConstraint, Index
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger('gapi.database')

# Load .env if available so DATABASE_URL can be picked up
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

def _load_database_url() -> str:
    """Load DATABASE_URL from env or config.json."""
    env_url = os.getenv('DATABASE_URL')
    if env_url:
        return env_url

    config_path = os.getenv('GAPI_CONFIG_PATH', 'config.json')
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                data = json.load(f)
            config_url = data.get('database_url')
            if isinstance(config_url, str) and config_url.strip():
                return config_url.strip()
    except Exception as e:
        logger.warning("Failed to read database_url from config: %s", e)

    return 'postgresql://gapi:gapi_password@localhost:5432/gapi_db'


# Database URL - adjust for your PostgreSQL setup
DATABASE_URL = _load_database_url()

Base = declarative_base()

try:
    # Configure PostgreSQL connection with UTF-8 encoding for Unicode support
    connect_args = {}
    if DATABASE_URL.startswith('postgresql'):
        connect_args = {'client_encoding': 'utf8'}
    
    engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
except Exception as e:
    logger.warning(f"PostgreSQL not available, will use mock database: {e}")
    engine = None
    SessionLocal = None


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True)
)


class Role(Base):
    """Role for access control."""
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, index=True)

    users = relationship("User", secondary=user_roles, back_populates="roles")


class User(Base):
    """User account with platform IDs."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, index=True)
    password = Column(String(64), nullable=False)  # SHA256 hash
    steam_id = Column(String(20), nullable=True)
    discord_id = Column(String(50), nullable=True, index=True)  # Discord user ID
    epic_id = Column(String(255), nullable=True)
    gog_id = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)                  # email for notifications
    # Profile card fields
    display_name = Column(String(255), nullable=True)       # shown instead of username
    bio = Column(String(500), nullable=True)                # short status / bio
    avatar_url = Column(String(500), nullable=True)         # custom avatar image URL
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_seen = Column(DateTime, nullable=True)  # Last activity timestamp for presence
    # Account suspension / ban (Item 5)
    is_suspended = Column(Boolean, default=False, nullable=False)
    suspended_until = Column(DateTime, nullable=True)       # None = permanent ban
    suspended_reason = Column(String(500), nullable=True)
    suspended_by = Column(String(255), nullable=True)       # admin who issued the suspension
    suspended_at = Column(DateTime, nullable=True)
    
    # Relationships
    roles = relationship("Role", secondary=user_roles, back_populates="users")
    favorites = relationship("FavoriteGame", back_populates="user", cascade="all, delete-orphan")
    ignored_games = relationship("IgnoredGame", back_populates="user", cascade="all, delete-orphan")
    achievements = relationship("Achievement", back_populates="user", cascade="all, delete-orphan")
    game_libraries = relationship("GameLibraryCache", back_populates="user", cascade="all, delete-orphan")


class FavoriteGame(Base):
    """Favorite games per user."""
    __tablename__ = "favorite_games"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    app_id = Column(String(50), index=True)
    platform = Column(String(50), default='steam')
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="favorites")


class IgnoredGame(Base):
    """Games the user is not interested in (don't recommend)."""
    __tablename__ = "ignored_games"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    app_id = Column(String(50), index=True)  # Steam app ID
    game_name = Column(String(500))
    reason = Column(String(500), nullable=True)  # e.g., "Already played", "Not interested"
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="ignored_games")


class Achievement(Base):
    """Track game achievements for users."""
    __tablename__ = "achievements"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    app_id = Column(String(50), index=True)
    game_name = Column(String(500))
    achievement_id = Column(String(255))
    achievement_name = Column(String(500))
    achievement_description = Column(Text, nullable=True)
    unlocked = Column(Boolean, default=False)
    unlock_time = Column(DateTime, nullable=True)
    rarity = Column(Float, nullable=True)  # Percentage (0-100)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="achievements")


class AchievementHunt(Base):
    """Track achievement hunting sessions."""
    __tablename__ = "achievement_hunts"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    app_id = Column(String(50))
    game_name = Column(String(500))
    difficulty = Column(String(50))  # 'easy', 'medium', 'hard', 'extreme'
    target_achievements = Column(Integer, default=0)
    unlocked_achievements = Column(Integer, default=0)
    progress_percent = Column(Float, default=0.0)
    status = Column(String(50), default='in_progress')  # 'in_progress', 'completed', 'abandoned'
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id])


class AchievementChallenge(Base):
    """Multiplayer achievement challenge shared between users."""
    __tablename__ = "achievement_challenges"

    id = Column(Integer, primary_key=True)
    challenge_id = Column(String(20), unique=True, index=True)  # short human-readable ID
    title = Column(String(255), nullable=False)
    app_id = Column(String(50), nullable=False)
    game_name = Column(String(500), nullable=False)
    # comma-separated achievement_ids; NULL means all achievements count
    target_achievement_ids = Column(Text, nullable=True)
    status = Column(String(50), default='open')  # 'open', 'in_progress', 'completed', 'cancelled'
    created_by = Column(Integer, ForeignKey("users.id"))
    winner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
    winner = relationship("User", foreign_keys=[winner_user_id])
    participants = relationship(
        "ChallengeParticipant", back_populates="challenge", cascade="all, delete-orphan"
    )


class ChallengeParticipant(Base):
    """Participation record for a single user in an AchievementChallenge."""
    __tablename__ = "challenge_participants"

    id = Column(Integer, primary_key=True)
    challenge_id = Column(Integer, ForeignKey("achievement_challenges.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    unlocked_count = Column(Integer, default=0)
    completed = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    challenge = relationship("AchievementChallenge", back_populates="participants")
    user = relationship("User", foreign_keys=[user_id])


class GameLibraryCache(Base):
    """Cache user's Steam/Epic/GOG game library for faster access."""
    __tablename__ = "game_library_cache"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    app_id = Column(String(50), index=True)
    game_name = Column(String(500))
    platform = Column(String(50))  # 'steam', 'epic', 'gog'
    playtime_hours = Column(Float, default=0.0)
    last_played = Column(DateTime, nullable=True)
    cached_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="game_libraries")


class GameDetailsCache(Base):
    """Cache game details from Steam/Epic/GOG for faster access and lazy loading."""
    __tablename__ = "game_details_cache"
    
    id = Column(Integer, primary_key=True)
    app_id = Column(String(50), index=True)
    platform = Column(String(50))  # 'steam', 'epic', 'gog'
    details_json = Column(Text)  # JSON serialized details
    cached_at = Column(DateTime, default=datetime.utcnow)
    
    # Store last API check time to implement 1-hour TTL
    last_api_check = Column(DateTime, default=datetime.utcnow)
    
    # Unique constraint on app_id + platform combination
    __table_args__ = (
        UniqueConstraint('app_id', 'platform', name='uq_app_id_platform'),
    )


class MultiUserSession(Base):
    """Track multi-user game picking sessions."""
    __tablename__ = "multiuser_sessions"
    
    id = Column(Integer, primary_key=True)
    session_id = Column(String(255), unique=True, index=True)
    participants = Column(Text)  # JSON array of usernames
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    shared_ignores = Column(Boolean, default=False)  # Whether to use shared ignore rules
    game_picked = Column(String(50), nullable=True)
    picked_at = Column(DateTime, nullable=True)


class UserFriendship(Base):
    """In-app friendship between two GAPI users (with request/accept flow)."""
    __tablename__ = "user_friendships"

    id = Column(Integer, primary_key=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    addressee_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # status: 'pending' | 'accepted' | 'declined'
    status = Column(String(20), default='pending', nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    requester = relationship("User", foreign_keys=[requester_id])
    addressee = relationship("User", foreign_keys=[addressee_id])

    __table_args__ = (
        UniqueConstraint('requester_id', 'addressee_id', name='uq_friendship_pair'),
    )


class Notification(Base):
    """In-app notifications / alerts for users."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String(50), default='info')   # 'info', 'warning', 'success', 'error', 'friend_request'
    title = Column(String(255))
    message = Column(Text)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])


class ChatMessage(Base):
    """In-app chat messages between users."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # recipient_id=None means it's a global/room message
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    room = Column(String(100), default='general')  # channel / room name
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    edited_at = Column(DateTime, nullable=True)  # When message was last edited
    deleted_at = Column(DateTime, nullable=True)  # Soft delete timestamp
    reply_to_id = Column(Integer, ForeignKey("chat_messages.id"), nullable=True)  # For threading
    command_only = Column(Boolean, default=False)  # Only visible to sender and admins

    sender = relationship("User", foreign_keys=[sender_id])
    recipient = relationship("User", foreign_keys=[recipient_id])
    reply_to = relationship("ChatMessage", remote_side=[id], foreign_keys=[reply_to_id])


class ChatMessageReaction(Base):
    """Reactions (emojis) on chat messages."""
    __tablename__ = "chat_message_reactions"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    emoji = Column(String(20), nullable=False)  # Emoji unicode or shortcode
    created_at = Column(DateTime, default=datetime.utcnow)

    message = relationship("ChatMessage")
    user = relationship("User")

    __table_args__ = (
        # One user can only react once with each emoji per message
        Index('idx_message_user_emoji', 'message_id', 'user_id', 'emoji', unique=True),
    )


class Plugin(Base):
    """Registered addons / plugins."""
    __tablename__ = "plugins"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    version = Column(String(50), default='1.0.0')
    author = Column(String(255), nullable=True)
    enabled = Column(Boolean, default=True)
    config_json = Column(Text, nullable=True)  # JSON plugin config/settings
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppSettings(Base):
    """Admin-controlled global application settings stored as key/value pairs."""
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=True)
    description = Column(String(500), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String(255), nullable=True)  # username of last editor


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 9: ADMIN EXCELLENCE & USER EXPERIENCE FEATURES
# ═══════════════════════════════════════════════════════════════════════════

class AuditLog(Base):
    """Audit trail for tracking all admin actions and user activities."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, index=True)
    action = Column(String(100), nullable=False)  # 'login', 'pick', 'review', 'delete_user', etc.
    resource_type = Column(String(100), nullable=True)  # 'game', 'user', 'review', 'chat', etc.
    resource_id = Column(String(255), nullable=True)  # game_id, user_id, etc.
    description = Column(Text, nullable=True)  # Human-readable description
    old_value = Column(Text, nullable=True)  # JSON string of old data
    new_value = Column(Text, nullable=True)  # JSON string of new data
    ip_address = Column(String(255), nullable=True)
    user_agent = Column(Text, nullable=True)
    status = Column(String(50), default='success')  # success, failure, error
    error_message = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class UserReport(Base):
    """User-generated reports for moderation."""
    __tablename__ = "user_reports"

    id = Column(Integer, primary_key=True)
    reporter_username = Column(String(255), nullable=False, index=True)
    reported_username = Column(String(255), nullable=True)  # Null if reporting content
    report_type = Column(String(50), nullable=False)  # 'user', 'chat', 'review', 'game_pick'
    resource_type = Column(String(100), nullable=True)  # 'chat_message', 'review', etc.
    resource_id = Column(String(255), nullable=True)
    reason = Column(String(255), nullable=False)  # 'spam', 'profanity', 'harassment', 'cheating', etc.
    description = Column(Text, nullable=True)
    status = Column(String(50), default='pending')  # pending, investigating, resolved, dismissed
    priority = Column(Integer, default=0)  # 0=low, 1=medium, 2=high
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String(255), nullable=True)  # Moderator username


class ModerationLog(Base):
    """Log of moderation actions taken by admins."""
    __tablename__ = "moderation_logs"

    id = Column(Integer, primary_key=True)
    moderator_username = Column(String(255), nullable=False, index=True)
    action = Column(String(100), nullable=False)  # 'warn', 'mute', 'ban', 'suspend', 'delete_content', etc.
    target_username = Column(String(255), nullable=True)
    target_content_id = Column(String(255), nullable=True)  # If action is on content
    reason = Column(String(255), nullable=False)
    duration = Column(Integer, nullable=True)  # Duration in minutes (for temp bans/mutes)
    notes = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    expires_at = Column(DateTime, nullable=True)  # When temporary moderation expires


class ProfanityFilter(Base):
    """Configurable profanity filter word list."""
    __tablename__ = "profanity_filters"

    id = Column(Integer, primary_key=True)
    word = Column(String(255), unique=True, nullable=False, index=True)
    severity = Column(Integer, default=1)  # 1=low, 2=medium, 3=high
    auto_action = Column(String(50), default='flag')  # flag, warn, mute, none
    enabled = Column(Boolean, default=True)
    added_by = Column(String(255), nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow)


class SavedSearch(Base):
    """User-saved searches for quick access."""
    __tablename__ = "saved_searches"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, index=True)
    search_name = Column(String(255), nullable=False)
    query = Column(String(500), nullable=False)  # Search query string
    filters = Column(Text, nullable=True)  # JSON filters (genre, year, etc.)
    pinned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    use_count = Column(Integer, default=0)


class SearchHistory(Base):
    """Per-user search history — last N searches for autocomplete & analytics."""
    __tablename__ = "search_history"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, index=True)
    query = Column(String(500), nullable=False)
    filters = Column(Text, nullable=True)   # JSON
    result_count = Column(Integer, nullable=True)
    searched_at = Column(DateTime, default=datetime.utcnow, index=True)


# ---------------------------------------------------------------------------
# Fine-grained Permission System  (Tier 2, item 5)
# ---------------------------------------------------------------------------

# Built-in permission set. ``'*'`` means "all permissions".
PERMISSIONS: dict = {
    'admin': ['*'],
    'moderator': ['moderate_chat', 'flag_reviews', 'manage_users',
                  'view_audit_logs', 'manage_reports'],
    'creator': ['create_content', 'stream', 'analytics_read'],
    'vip': ['early_access', 'cosmetics', 'analytics_read'],
    'user': ['analytics_read'],
}

# Complete list of discrete permissions available in the system.
ALL_PERMISSIONS: list = [
    'analytics_read',
    'create_content',
    'cosmetics',
    'early_access',
    'flag_reviews',
    'manage_reports',
    'manage_users',
    'moderate_chat',
    'stream',
    'view_audit_logs',
]


class UserPermission(Base):
    """Per-user permission overrides (grants or explicit denials on top of role perms)."""
    __tablename__ = "user_permissions"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, index=True)
    permission = Column(String(100), nullable=False, index=True)
    granted = Column(Boolean, default=True)   # True = grant, False = explicit deny
    granted_by = Column(String(255), nullable=True)
    granted_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint('username', 'permission', name='uq_user_permission'),)


# ---------------------------------------------------------------------------
# Notification Preferences  (Tier 2, item 6)
# ---------------------------------------------------------------------------

class UserNotificationPreference(Base):
    """Per-user notification channel / category preferences."""
    __tablename__ = "user_notification_preferences"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, unique=True, index=True)
    email_enabled = Column(Boolean, default=False)
    push_enabled = Column(Boolean, default=True)
    friend_requests = Column(Boolean, default=True)
    challenge_updates = Column(Boolean, default=True)
    trade_offers = Column(Boolean, default=True)
    team_events = Column(Boolean, default=True)
    system_announcements = Column(Boolean, default=True)
    digest_frequency = Column(String(20), default='never')   # 'never','daily','weekly'
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



# ---------------------------------------------------------------------------
# User Reputation / Trust Score  (Item 7 — Content Moderation)
# ---------------------------------------------------------------------------

class UserReputation(Base):
    """Reputation (trust) score for each user.

    Score starts at 100 and is decremented when moderation actions are taken.
    Automatic bans are triggered when the score falls below
    ``REPUTATION_AUTO_BAN_THRESHOLD``.
    """
    __tablename__ = "user_reputations"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    score = Column(Integer, default=100, nullable=False)         # 0–200, starts at 100
    violation_count = Column(Integer, default=0, nullable=False) # total moderation actions
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_action = Column(String(255), nullable=True)             # most recent action label


# Score deducted per moderation action severity
REPUTATION_PENALTIES: dict = {
    'warn': 5,
    'mute': 10,
    'suspend': 20,
    'ban': 40,
    'delete_content': 3,
    'default': 5,
}

# Score below which an automatic suspension is issued
REPUTATION_AUTO_BAN_THRESHOLD: int = 40

# Starting reputation score for new users
REPUTATION_DEFAULT_SCORE: int = 100


# ---------------------------------------------------------------------------
# User Groups  (Item 5 — Advanced User Management)
# ---------------------------------------------------------------------------

class UserGroup(Base):
    """Admin-defined user groups for bulk permission/role management."""
    __tablename__ = "user_groups"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserGroupMember(Base):
    """Membership record linking a user to a group."""
    __tablename__ = "user_group_members"

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("user_groups.id"), nullable=False, index=True)
    username = Column(String(255), nullable=False, index=True)
    added_by = Column(String(255), nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint('group_id', 'username', name='uq_group_member'),)


# ---------------------------------------------------------------------------
# A/B Testing Framework for Recommendations  (Tier 4 / Item 13)
# ---------------------------------------------------------------------------

class RecommendationExperiment(Base):
    """A/B experiment definition for recommendation algorithms."""
    __tablename__ = "recommendation_experiments"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    # Comma-separated variant names, e.g. "control,collaborative,ml"
    variants = Column(Text, nullable=False, default='control,treatment')
    # 'draft' | 'active' | 'paused' | 'concluded'
    status = Column(String(50), default='draft', index=True)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)


class ExperimentAssignment(Base):
    """Records which variant a user is assigned to for a given experiment."""
    __tablename__ = "experiment_assignments"

    id = Column(Integer, primary_key=True)
    experiment_id = Column(Integer, ForeignKey("recommendation_experiments.id"), nullable=False, index=True)
    username = Column(String(255), nullable=False, index=True)
    variant = Column(String(100), nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint('experiment_id', 'username', name='uq_exp_user'),)


def get_db():
    """Get database session."""
    if SessionLocal:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    else:
        yield None


def init_db():
    """Initialize database tables."""
    if engine:
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables initialized successfully")
            
            # Run migrations
            # Disabled automatic migration - run manually if needed
            # _run_migrations()
            return True
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            return False
    return False


def _run_migrations():
    """Run database migrations."""
    if not engine:
        return
    
    # Migrate: Add command_only column to chat_messages if it doesn't exist
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(engine)
        
        if 'chat_messages' in inspector.get_table_names():
            columns = {col['name'] for col in inspector.get_columns('chat_messages')}
            
            if 'command_only' not in columns:
                with engine.connect() as conn:
                    # Determine database type and use appropriate SQL
                    dialect_name = engine.dialect.name
                    
                    if dialect_name == 'sqlite':
                        conn.execute(text('ALTER TABLE chat_messages ADD COLUMN command_only BOOLEAN DEFAULT 0'))
                    elif dialect_name == 'postgresql':
                        conn.execute(text('ALTER TABLE chat_messages ADD COLUMN command_only BOOLEAN DEFAULT false'))
                    else:
                        # SQL Server and others
                        conn.execute(text('ALTER TABLE chat_messages ADD command_only BIT DEFAULT 0'))
                    
                    conn.commit()
                    logger.info("Migrated: Added command_only column to chat_messages")
    except Exception as e:
        logger.warning(f"Migration check failed (may already be applied): {e}")


def get_user_by_username(db, username: str):
    """Get user from database."""
    if not db:
        return None
    try:
        return db.query(User).filter(User.username == username).first()
    except Exception as e:
        logger.error(f"Error getting user: {e}")
        return None


def user_exists(db, username: str) -> bool:
    """Return True if a user with *username* exists in the database.

    Args:
        db:       SQLAlchemy session.
        username: Username to look up.

    Returns:
        ``True`` when the user exists, ``False`` otherwise or on error.
    """
    return get_user_by_username(db, username) is not None


def get_user_email(db, username: str) -> str:
    """Return the email address stored for *username*, or an empty string.

    Args:
        db:       SQLAlchemy session.
        username: Username to look up.

    Returns:
        The user's email address, or ``''`` when not set or on error.
    """
    if not db or not username:
        return ''
    try:
        user = get_user_by_username(db, username)
        if user and getattr(user, 'email', None):
            return user.email
        return ''
    except Exception:
        return ''


def set_user_email(db, username: str, email: str) -> bool:
    """Set (or update) the email address for *username*.

    Args:
        db:       SQLAlchemy session.
        username: Target username.
        email:    New email address.  Pass ``''`` or ``None`` to clear it.

    Returns:
        ``True`` on success, ``False`` on error.
    """
    if not db or not username:
        return False
    try:
        user = get_user_by_username(db, username)
        if not user:
            return False
        user.email = email.strip() if email else None
        db.commit()
        return True
    except Exception as e:
        logger.error('set_user_email error: %s', e)
        db.rollback()
        return False


def ensure_role(db, role_name: str) -> Role:
    """Ensure a role exists and return it."""
    if not db:
        return None
    role = db.query(Role).filter(Role.name == role_name).first()
    if role:
        return role
    role = Role(name=role_name)
    db.add(role)
    db.commit()
    return role


def get_user_roles(db, username: str) -> list:
    """Get a list of role names for a user."""
    if not db:
        return []
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return []
    return [r.name for r in user.roles]


def get_roles(db) -> list:
    """Get all role names."""
    if not db:
        return []
    try:
        roles = db.query(Role).order_by(Role.name).all()
        return [r.name for r in roles]
    except Exception as e:
        logger.error(f"Error getting roles: {e}")
        return []


def set_user_roles(db, username: str, roles: list) -> bool:
    """Set roles for a user (replaces existing roles)."""
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False
        role_objects = [ensure_role(db, r) for r in roles if r]
        user.roles = [r for r in role_objects if r]
        user.updated_at = datetime.utcnow()
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error setting user roles: {e}")
        db.rollback()
        return False


def create_or_update_user(db, username: str, password: str = '', steam_id: str = '', epic_id: str = '', gog_id: str = '', role: str = 'user', roles: list = None):
    """Create or update user in database.
    
    Args:
        db: Database session
        username: Username
        password: Password hash (SHA256). If empty and user exists, password is not updated.
        steam_id: Steam ID
        epic_id: Epic Games ID
        gog_id: GOG ID
        role: User role ('admin' or 'user')
        roles: Optional list of role names to assign (overrides role param)
    """
    if not db:
        return None
    try:
        user = db.query(User).filter(User.username == username).first()
        if user:
            # Update existing user
            if password:  # Only update password if provided
                user.password = password
            user.steam_id = steam_id
            user.epic_id = epic_id
            user.gog_id = gog_id
            user.updated_at = datetime.utcnow()
        else:
            # Create new user - password is required
            if not password:
                logger.error("Password required for new user")
                return None
            user = User(
                username=username,
                password=password,
                steam_id=steam_id,
                epic_id=epic_id,
                gog_id=gog_id
            )
            db.add(user)

        # Assign roles
        role_names = roles if isinstance(roles, list) and roles else [role]
        role_objects = [ensure_role(db, r) for r in role_names if r]
        user.roles = [r for r in role_objects if r]
        db.commit()
        return user
    except Exception as e:
        logger.error(f"Error creating/updating user: {e}")
        db.rollback()
        return None


def get_ignored_games(db, username: str):
    """Get list of ignored game IDs for a user."""
    if not db:
        return []
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return []
        return [ig.app_id for ig in user.ignored_games]
    except Exception as e:
        logger.error(f"Error getting ignored games: {e}")
        return []


def toggle_ignore_game(db, username: str, app_id: str, game_name: str = '', reason: str = ''):
    """Toggle game ignore status for user."""
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False
        
        # Check if already ignored
        ignored = db.query(IgnoredGame).filter(
            IgnoredGame.user_id == user.id,
            IgnoredGame.app_id == str(app_id)
        ).first()
        
        if ignored:
            # Remove from ignore list
            db.delete(ignored)
        else:
            # Add to ignore list
            new_ignore = IgnoredGame(
                user_id=user.id,
                app_id=str(app_id),
                game_name=game_name,
                reason=reason
            )
            db.add(new_ignore)
        
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error toggling ignore: {e}")
        db.rollback()
        return False


def get_shared_ignore_games(db, usernames: list):
    """Get games ignored by ALL users in a list (for shared ignore rules)."""
    if not db or not usernames:
        return []
    try:
        # Get all ignored games for each user
        all_ignored_sets = []
        for username in usernames:
            user = db.query(User).filter(User.username == username).first()
            if user:
                ignored_ids = set([ig.app_id for ig in user.ignored_games])
                all_ignored_sets.append(ignored_ids)
        
        if not all_ignored_sets:
            return []
        
        # Return only games that are ignored by ALL users
        shared_ignores = all_ignored_sets[0]
        for ignored_set in all_ignored_sets[1:]:
            shared_ignores = shared_ignores.intersection(ignored_set)
        
        return list(shared_ignores)
    except Exception as e:
        logger.error(f"Error getting shared ignores: {e}")
        return []


def get_all_users(db):
    """Get all users from the database."""
    if not db:
        return []
    try:
        users = db.query(User).all()
        return users
    except Exception as e:
        logger.error(f"Error getting all users: {e}")
        return []


def delete_user(db, username: str):
    """Delete a user from the database."""
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if user:
            db.delete(user)
            db.commit()
            return True
        return False
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        db.rollback()
        return False


def update_user_role(db, username: str, role: str):
    """Update user's role."""
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if user:
            role_obj = ensure_role(db, role)
            user.roles = [role_obj] if role_obj else []
            user.updated_at = datetime.utcnow()
            db.commit()
            return True
        return False
    except Exception as e:
        logger.error(f"Error updating user role: {e}")
        db.rollback()
        return False


def verify_user_password(db, username: str, password_hash: str):
    """Verify a user's password hash."""
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if user and user.password == password_hash:
            return True
        return False
    except Exception as e:
        logger.error(f"Error verifying password: {e}")
        return False


def get_user_count(db) -> int:
    """Get total number of users."""
    if not db:
        return 0
    try:
        return db.query(User).count()
    except Exception as e:
        logger.error(f"Error getting user count: {e}")
        return 0


def get_cached_library(db, username: str):
    """Get cached game library for a user."""
    if not db:
        return []
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return []
        
        games = db.query(GameLibraryCache).filter(
            GameLibraryCache.user_id == user.id
        ).order_by(GameLibraryCache.game_name).all()
        
        return [{
            'app_id': g.app_id,
            'name': g.game_name,
            'platform': g.platform,
            'playtime_hours': g.playtime_hours,
            'last_played': g.last_played,
            'cached_at': g.cached_at
        } for g in games]
    except Exception as e:
        logger.error(f"Error getting cached library: {e}")
        return []


def cache_user_library(db, username: str, games: list):
    """Cache user's game library in the database.
    
    Args:
        db: Database session
        username: Username
        games: List of game dicts with keys: app_id, name, platform, playtime_hours, last_played
    
    Returns:
        Number of games cached
    """
    if not db:
        return 0
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            logger.error(f"User {username} not found")
            return 0
        
        # Delete existing cache for this user
        db.query(GameLibraryCache).filter(GameLibraryCache.user_id == user.id).delete()
        
        # Add new cache entries
        count = 0
        for game in games:
            try:
                # Ensure game name is properly encoded as UTF-8
                game_name = game.get('name', 'Unknown')
                if isinstance(game_name, bytes):
                    game_name = game_name.decode('utf-8', errors='replace')
                elif isinstance(game_name, str):
                    # Ensure it's valid UTF-8 by encoding and decoding
                    game_name = game_name.encode('utf-8', errors='replace').decode('utf-8')
                
                cache_entry = GameLibraryCache(
                    user_id=user.id,
                    app_id=str(game.get('app_id', game.get('appid', ''))),
                    game_name=game_name,
                    platform=game.get('platform', 'steam'),
                    playtime_hours=float(game.get('playtime_hours', game.get('playtime_forever', 0)) / 60 
                                       if 'playtime_forever' in game else game.get('playtime_hours', 0)),
                    last_played=game.get('last_played')
                )
                db.add(cache_entry)
                count += 1
            except Exception as game_error:
                logger.warning(f"Skipping game due to encoding error: {game.get('name', 'Unknown')}: {game_error}")
                continue
        
        db.commit()
        logger.info(f"Cached {count} games for user {username}")
        return count
    except Exception as e:
        logger.error(f"Error caching library: {e}")
        db.rollback()
        return 0


def get_library_cache_age(db, username: str):
    """Get the age of the cached library in seconds.
    
    Returns:
        Number of seconds since last cache, or None if no cache exists
    """
    if not db:
        return None
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return None
        
        latest = db.query(GameLibraryCache).filter(
            GameLibraryCache.user_id == user.id
        ).order_by(GameLibraryCache.cached_at.desc()).first()
        
        if not latest:
            return None
        
        age = (datetime.utcnow() - latest.cached_at).total_seconds()
        return age
    except Exception as e:
        logger.error(f"Error getting cache age: {e}")
        return None


def get_user_favorites(db, username: str) -> list:
    """Get user's favorite game IDs."""
    if not db:
        return []
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return []
        return [f.app_id for f in user.favorites]
    except Exception as e:
        logger.error(f"Error getting user favorites: {e}")
        return []


def add_favorite(db, username: str, app_id: str, platform: str = 'steam') -> bool:
    """Add a game to user's favorites."""
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False
        
        # Check if already favorited
        existing = db.query(FavoriteGame).filter(
            FavoriteGame.user_id == user.id,
            FavoriteGame.app_id == app_id
        ).first()
        
        if existing:
            return True
        
        favorite = FavoriteGame(user_id=user.id, app_id=app_id, platform=platform)
        db.add(favorite)
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error adding favorite: {e}")
        db.rollback()
        return False


def remove_favorite(db, username: str, app_id: str) -> bool:
    """Remove a game from user's favorites."""
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False
        
        favorite = db.query(FavoriteGame).filter(
            FavoriteGame.user_id == user.id,
            FavoriteGame.app_id == app_id
        ).first()
        
        if favorite:
            db.delete(favorite)
            db.commit()
        return True
    except Exception as e:
        logger.error(f"Error removing favorite: {e}")
        db.rollback()
        return False


def get_game_details_cache(db, app_id: str, platform: str = 'steam', max_age_hours: int = 1) -> dict:
    """Get cached game details if available and fresh.
    
    Args:
        db: Database session
        app_id: Game app ID
        platform: Platform name ('steam', 'epic', 'gog')
        max_age_hours: Maximum age in hours to consider cache fresh
        
    Returns:
        Cached details dict or None if not available/stale
    """
    if not db:
        return None
    try:
        cache = db.query(GameDetailsCache).filter(
            GameDetailsCache.app_id == str(app_id),
            GameDetailsCache.platform == platform.lower()
        ).first()
        
        if not cache:
            return None
        
        # Check if cache is still fresh (within max_age_hours)
        age_seconds = (datetime.utcnow() - cache.last_api_check).total_seconds()
        if age_seconds > max_age_hours * 3600:  # Older than max_age_hours
            return None  # Cache is stale
        
        # Parse and return cached details
        import json
        return json.loads(cache.details_json)
    except Exception as e:
        logger.error(f"Error getting game details cache: {e}")
        return None


def update_game_details_cache(db, app_id: str, platform: str, details: dict) -> bool:
    """Update game details cache.
    
    Args:
        db: Database session
        app_id: Game app ID
        platform: Platform name ('steam', 'epic', 'gog')
        details: Details dict to cache
        
    Returns:
        True if successful, False otherwise
    """
    if not db or not details:
        return False
    try:
        import json
        
        app_id_str = str(app_id)
        platform_lower = platform.lower()
        
        cache = db.query(GameDetailsCache).filter(
            GameDetailsCache.app_id == app_id_str,
            GameDetailsCache.platform == platform_lower
        ).first()
        
        if cache:
            # Update existing
            cache.details_json = json.dumps(details)
            cache.cached_at = datetime.utcnow()
            cache.last_api_check = datetime.utcnow()
        else:
            # Create new
            cache = GameDetailsCache(
                app_id=app_id_str,
                platform=platform_lower,
                details_json=json.dumps(details),
                cached_at=datetime.utcnow(),
                last_api_check=datetime.utcnow()
            )
            db.add(cache)
        
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating game details cache: {e}")
        db.rollback()
        return False


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

def create_notification(db, username: str, title: str, message: str, type: str = 'info') -> bool:
    """Create a notification for the given user."""
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False
        notif = Notification(user_id=user.id, type=type, title=title, message=message)
        db.add(notif)
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error creating notification: {e}")
        db.rollback()
        return False


def get_notifications(db, username: str, unread_only: bool = False) -> list:
    """Return notifications for the given user."""
    if not db:
        return []
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return []
        q = db.query(Notification).filter(Notification.user_id == user.id)
        if unread_only:
            q = q.filter(Notification.is_read.is_(False))
        notifs = q.order_by(Notification.created_at.desc()).limit(50).all()
        return [
            {
                'id': n.id,
                'type': n.type,
                'title': n.title,
                'message': n.message,
                'is_read': n.is_read,
                'created_at': n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifs
        ]
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return []


def mark_notifications_read(db, username: str, notification_ids: list = None) -> bool:
    """Mark notifications as read. If notification_ids is None, marks all."""
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False
        q = db.query(Notification).filter(Notification.user_id == user.id)
        if notification_ids:
            q = q.filter(Notification.id.in_(notification_ids))
        q.update({'is_read': True}, synchronize_session=False)
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error marking notifications read: {e}")
        db.rollback()
        return False


# ---------------------------------------------------------------------------
# Chat helpers
# ---------------------------------------------------------------------------

def send_chat_message(db, sender_username: str, message: str, room: str = 'general', recipient_username: str = None, command_only: bool = False, reply_to_id: int = None) -> dict:
    """Save a chat message and return it as a dict."""
    if not db:
        return {}
    try:
        sender = db.query(User).filter(User.username == sender_username).first()
        if not sender:
            return {}
        recipient_id = None
        if recipient_username:
            recipient = db.query(User).filter(User.username == recipient_username).first()
            if recipient:
                recipient_id = recipient.id
        
        # Try to create message with all new fields
        try:
            msg = ChatMessage(
                sender_id=sender.id,
                recipient_id=recipient_id,
                room=room,
                message=message,
                command_only=command_only,
                reply_to_id=reply_to_id,
            )
        except TypeError:
            # Fallback for older database schema
            msg = ChatMessage(
                sender_id=sender.id,
                recipient_id=recipient_id,
                room=room,
                message=message,
            )
        
        db.add(msg)
        db.commit()
        db.refresh(msg)
        
        result = {
            'id': msg.id,
            'sender': sender_username,
            'room': msg.room,
            'message': msg.message,
            'created_at': msg.created_at.isoformat() if msg.created_at else None,
        }
        
        # Handle new fields - may not exist in older databases
        try:
            result['command_only'] = msg.command_only
            result['reply_to_id'] = msg.reply_to_id
        except AttributeError:
            result['command_only'] = False
            result['reply_to_id'] = None
        
        return result
    except Exception as e:
        logger.error(f"Error sending chat message: {e}")
        db.rollback()
        return {}


def get_chat_messages(db, room: str = 'general', limit: int = 50, since_id: int = 0, before_id: int = 0) -> list:
    """Return recent messages from a room.
    
    Args:
        room: Chat room name
        limit: Maximum number of messages to return
        since_id: Return only messages with id > this value (for new messages)
        before_id: Return only messages with id < this value (for loading older messages)
    """
    if not db:
        return []
    try:
        q = db.query(ChatMessage).filter(ChatMessage.room == room, ChatMessage.deleted_at.is_(None))
        if since_id:
            q = q.filter(ChatMessage.id > since_id)
        if before_id:
            q = q.filter(ChatMessage.id < before_id)
        msgs = q.order_by(ChatMessage.created_at.desc() if before_id else ChatMessage.created_at.asc()).limit(limit).all()
        # Reverse if we fetched older messages (they come in desc order)
        if before_id:
            msgs = list(reversed(msgs))
        result = []
        for m in msgs:
            item = {
                'id': m.id,
                'sender': m.sender.username if m.sender else 'unknown',
                'room': m.room,
                'message': m.message,
                'created_at': m.created_at.isoformat() if m.created_at else None,
            }
            # Handle new fields - may not exist in older databases
            try:
                item['command_only'] = m.command_only
                item['edited_at'] = m.edited_at.isoformat() if m.edited_at else None
                item['reply_to_id'] = m.reply_to_id
                
                # If replying to another message, include preview of that message
                if m.reply_to_id and m.reply_to:
                    item['reply_to'] = {
                        'id': m.reply_to.id,
                        'sender': m.reply_to.sender.username if m.reply_to.sender else 'unknown',
                        'message': m.reply_to.message[:100] + ('...' if len(m.reply_to.message) > 100 else ''),
                    }
            except AttributeError:
                item['command_only'] = False
                item['edited_at'] = None
                item['reply_to_id'] = None
            
            # Get reactions for this message
            item['reactions'] = get_message_reactions(db, m.id)
            
            result.append(item)
        return result
    except Exception as e:
        logger.error(f"Error getting chat messages: {e}")
        return []


def get_message_reactions(db, message_id: int) -> dict:
    """Get reactions for a message grouped by emoji.
    Returns: {"👍": [{"username": "alice", "created_at": "..."}, ...], ...}
    """
    if not db:
        return {}
    try:
        reactions = db.query(ChatMessageReaction).filter(
            ChatMessageReaction.message_id == message_id
        ).order_by(ChatMessageReaction.created_at.asc()).all()
        
        grouped = {}
        for r in reactions:
            emoji = r.emoji
            if emoji not in grouped:
                grouped[emoji] = []
            grouped[emoji].append({
                'username': r.user.username if r.user else 'unknown',
                'created_at': r.created_at.isoformat() if r.created_at else None,
            })
        return grouped
    except Exception as e:
        logger.error(f"Error getting message reactions: {e}")
        return {}


def add_message_reaction(db, message_id: int, username: str, emoji: str) -> bool:
    """Add a reaction to a message. Returns True if successful."""
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False
        
        message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
        if not message:
            return False
        
        # Check if reaction already exists
        existing = db.query(ChatMessageReaction).filter(
            ChatMessageReaction.message_id == message_id,
            ChatMessageReaction.user_id == user.id,
            ChatMessageReaction.emoji == emoji
        ).first()
        
        if existing:
            # Already reacted with this emoji, do nothing
            return True
        
        reaction = ChatMessageReaction(
            message_id=message_id,
            user_id=user.id,
            emoji=emoji
        )
        db.add(reaction)
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error adding message reaction: {e}")
        db.rollback()
        return False


def remove_message_reaction(db, message_id: int, username: str, emoji: str) -> bool:
    """Remove a reaction from a message. Returns True if successful."""
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False
        
        reaction = db.query(ChatMessageReaction).filter(
            ChatMessageReaction.message_id == message_id,
            ChatMessageReaction.user_id == user.id,
            ChatMessageReaction.emoji == emoji
        ).first()
        
        if reaction:
            db.delete(reaction)
            db.commit()
        return True
    except Exception as e:
        logger.error(f"Error removing message reaction: {e}")
        db.rollback()
        return False


def edit_chat_message(db, message_id: int, username: str, new_text: str) -> bool:
    """Edit a chat message. Only the sender can edit. Returns True if successful."""
    if not db or not new_text.strip():
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False
        
        message = db.query(ChatMessage).filter(
            ChatMessage.id == message_id,
            ChatMessage.sender_id == user.id,
            ChatMessage.deleted_at.is_(None)
        ).first()
        
        if not message:
            return False
        
        message.message = new_text.strip()
        message.edited_at = datetime.utcnow()
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error editing chat message: {e}")
        db.rollback()
        return False


def delete_chat_message(db, message_id: int, username: str) -> bool:
    """Soft delete a chat message. Only the sender can delete. Returns True if successful."""
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False
        
        message = db.query(ChatMessage).filter(
            ChatMessage.id == message_id,
            ChatMessage.sender_id == user.id,
            ChatMessage.deleted_at.is_(None)
        ).first()
        
        if not message:
            return False
        
        message.deleted_at = datetime.utcnow()
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error deleting chat message: {e}")
        db.rollback()
        return False


# ---------------------------------------------------------------------------
# Plugin helpers
# ---------------------------------------------------------------------------

def get_plugins(db) -> list:
    """Return all registered plugins."""
    if not db:
        return []
    try:
        plugins = db.query(Plugin).order_by(Plugin.name).all()
        return [
            {
                'id': p.id,
                'name': p.name,
                'description': p.description,
                'version': p.version,
                'author': p.author,
                'enabled': p.enabled,
                'created_at': p.created_at.isoformat() if p.created_at else None,
            }
            for p in plugins
        ]
    except Exception as e:
        logger.error(f"Error getting plugins: {e}")
        return []


def register_plugin(db, name: str, description: str = '', version: str = '1.0.0', author: str = '', config: dict = None) -> bool:
    """Register a new plugin or update an existing one."""
    if not db:
        return False
    try:
        existing = db.query(Plugin).filter(Plugin.name == name).first()
        if existing:
            existing.description = description
            existing.version = version
            existing.author = author
            existing.config_json = json.dumps(config) if config else None
            existing.updated_at = datetime.utcnow()
        else:
            plugin = Plugin(
                name=name,
                description=description,
                version=version,
                author=author,
                config_json=json.dumps(config) if config else None,
            )
            db.add(plugin)
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error registering plugin: {e}")
        db.rollback()
        return False


def toggle_plugin(db, plugin_id: int, enabled: bool) -> bool:
    """Enable or disable a plugin."""
    if not db:
        return False
    try:
        plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
        if not plugin:
            return False
        plugin.enabled = enabled
        plugin.updated_at = datetime.utcnow()
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error toggling plugin: {e}")
        db.rollback()
        return False


# ---------------------------------------------------------------------------
# Leaderboard helpers
# ---------------------------------------------------------------------------

def delete_plugin(db, plugin_id: int) -> bool:
    """Permanently delete a registered plugin.

    Args:
        db:        SQLAlchemy session.
        plugin_id: Primary-key ID of the plugin to delete.

    Returns:
        ``True`` if the plugin was found and deleted, ``False`` otherwise.
    """
    if not db:
        return False
    try:
        plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
        if not plugin:
            return False
        db.delete(plugin)
        db.commit()
        return True
    except Exception as e:
        logger.error("Error deleting plugin %s: %s", plugin_id, e)
        db.rollback()
        return False


def get_user_data_export(db, username: str) -> dict:
    """Collect all persisted data for *username* into a single exportable dict.

    The returned structure is designed to be round-tripped through
    :func:`import_user_data` to restore a user's data on the same or a
    different GAPI instance.

    Keys in the returned dict:
      - ``version``       – schema version string
      - ``exported_at``   – ISO-8601 UTC timestamp
      - ``username``      – the exporting user
      - ``profile``       – ``{steam_id, epic_id, gog_id}``
      - ``ignored_games`` – list of ``{app_id, game_name, reason}``
      - ``favorites``     – list of ``{app_id, platform}``
      - ``achievements``  – list of ``{app_id, game_name, achievement_id, name, unlocked, …}``
    """
    if not db:
        return {}
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return {}

        profile = {
            'steam_id': user.steam_id,
            'epic_id': user.epic_id,
            'gog_id': user.gog_id,
        }

        ignored = [
            {'app_id': ig.app_id, 'game_name': ig.game_name or '', 'reason': ig.reason or ''}
            for ig in user.ignored_games
        ]

        favorites = [
            {'app_id': f.app_id, 'platform': f.platform or 'steam'}
            for f in user.favorites
        ]

        achievements_out = []
        for a in user.achievements:
            achievements_out.append({
                'app_id': a.app_id,
                'game_name': a.game_name or '',
                'achievement_id': a.achievement_id,
                'name': a.achievement_name or '',
                'description': a.achievement_description or '',
                'unlocked': bool(a.unlocked),
                'unlock_time': a.unlock_time.isoformat() if a.unlock_time else None,
                'rarity': a.rarity,
            })

        return {
            'version': '1',
            'exported_at': datetime.utcnow().isoformat(),
            'username': username,
            'profile': profile,
            'ignored_games': ignored,
            'favorites': favorites,
            'achievements': achievements_out,
        }
    except Exception as e:
        logger.error("Error building user data export for %s: %s", username, e)
        return {}


def import_user_data(db, username: str, data: dict) -> dict:
    """Restore a user's data from an export dict produced by :func:`get_user_data_export`.

    This is a **merge** operation — existing records are not removed; new ones
    are added only if they are not already present.  The function returns a
    summary dict with counts of items processed.

    Args:
        db:       SQLAlchemy session.
        username: The user to import into (must already exist).
        data:     Export dict as produced by :func:`get_user_data_export`.

    Returns:
        ``{'ignored_added', 'favorites_added', 'achievements_added'}`` counts,
        or ``{}`` on failure.
    """
    if not db:
        return {}
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return {}

        counts = {'ignored_added': 0, 'favorites_added': 0, 'achievements_added': 0}

        # --- ignored games ---
        existing_ignored = {ig.app_id for ig in user.ignored_games}
        for item in data.get('ignored_games', []):
            app_id = str(item.get('app_id', '')).strip()
            if not app_id or app_id in existing_ignored:
                continue
            db.add(IgnoredGame(
                user_id=user.id,
                app_id=app_id,
                game_name=item.get('game_name', ''),
                reason=item.get('reason', ''),
            ))
            existing_ignored.add(app_id)
            counts['ignored_added'] += 1

        # --- favorites ---
        existing_favs = {f.app_id for f in user.favorites}
        for item in data.get('favorites', []):
            app_id = str(item.get('app_id', '')).strip()
            if not app_id or app_id in existing_favs:
                continue
            db.add(FavoriteGame(
                user_id=user.id,
                app_id=app_id,
                platform=item.get('platform', 'steam'),
            ))
            existing_favs.add(app_id)
            counts['favorites_added'] += 1

        # --- achievements ---
        existing_ach = {(a.app_id, a.achievement_id) for a in user.achievements}
        for item in data.get('achievements', []):
            app_id = str(item.get('app_id', '')).strip()
            ach_id = str(item.get('achievement_id', '')).strip()
            if not app_id or not ach_id or (app_id, ach_id) in existing_ach:
                continue
            unlock_time = None
            raw_ts = item.get('unlock_time')
            if raw_ts:
                try:
                    from datetime import datetime as _dt
                    unlock_time = _dt.fromisoformat(raw_ts)
                except Exception:
                    pass
            db.add(Achievement(
                user_id=user.id,
                app_id=app_id,
                game_name=item.get('game_name', ''),
                achievement_id=ach_id,
                achievement_name=item.get('name', ''),
                achievement_description=item.get('description', ''),
                unlocked=bool(item.get('unlocked', False)),
                unlock_time=unlock_time,
                rarity=item.get('rarity'),
            ))
            existing_ach.add((app_id, ach_id))
            counts['achievements_added'] += 1

        db.commit()
        return counts
    except Exception as e:
        logger.error("Error importing user data for %s: %s", username, e)
        db.rollback()
        return {}


def get_leaderboard(db, metric: str = 'playtime', limit: int = 20) -> list:
    """Return a leaderboard of users ranked by the given metric.

    Supported metrics: 'playtime', 'games', 'achievements'.
    """
    if not db:
        return []
    try:
        from sqlalchemy import func
        if metric == 'playtime':
            rows = (
                db.query(User.username, func.coalesce(func.sum(GameLibraryCache.playtime_hours), 0).label('score'))
                .outerjoin(GameLibraryCache, GameLibraryCache.user_id == User.id)
                .group_by(User.id, User.username)
                .order_by(func.coalesce(func.sum(GameLibraryCache.playtime_hours), 0).desc())
                .limit(limit)
                .all()
            )
        elif metric == 'games':
            rows = (
                db.query(User.username, func.count(GameLibraryCache.id).label('score'))
                .outerjoin(GameLibraryCache, GameLibraryCache.user_id == User.id)
                .group_by(User.id, User.username)
                .order_by(func.count(GameLibraryCache.id).desc())
                .limit(limit)
                .all()
            )
        elif metric == 'achievements':
            rows = (
                db.query(User.username, func.count(Achievement.id).label('score'))
                .outerjoin(Achievement, Achievement.user_id == User.id)
                .filter((Achievement.unlocked.is_(True)) | (Achievement.id.is_(None)))
                .group_by(User.id, User.username)
                .order_by(func.count(Achievement.id).desc())
                .limit(limit)
                .all()
            )
        else:
            return []
        return [
            {'rank': i + 1, 'username': row.username, 'score': round(float(row.score), 1)}
            for i, row in enumerate(rows)
        ]
    except Exception as e:
        logger.error(f"Error getting leaderboard: {e}")
        return []


# ---------------------------------------------------------------------------
# User profile card helpers
# ---------------------------------------------------------------------------

def get_user_card(db, username: str) -> dict:
    """Return a rich profile-card dict for the given user.

    Includes display name, bio, avatar, roles, stats (games, playtime,
    achievements), join date, and platform IDs.
    """
    if not db:
        return {}
    try:
        from sqlalchemy import func
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return {}

        # Aggregate stats
        total_games = db.query(func.count(GameLibraryCache.id)).filter(
            GameLibraryCache.user_id == user.id
        ).scalar() or 0

        total_playtime = db.query(func.coalesce(func.sum(GameLibraryCache.playtime_hours), 0)).filter(
            GameLibraryCache.user_id == user.id
        ).scalar() or 0

        total_achievements = db.query(func.count(Achievement.id)).filter(
            Achievement.user_id == user.id,
            Achievement.unlocked.is_(True)
        ).scalar() or 0

        roles = [r.name for r in user.roles]

        return {
            'username': user.username,
            'display_name': user.display_name or user.username,
            'bio': user.bio or '',
            'avatar_url': user.avatar_url or '',
            'roles': roles,
            'steam_id': user.steam_id or '',
            'stats': {
                'total_games': int(total_games),
                'total_playtime_hours': round(float(total_playtime), 1),
                'total_achievements': int(total_achievements),
            },
            'joined': user.created_at.isoformat() if user.created_at else None,
        }
    except Exception as e:
        logger.error(f"Error getting user card: {e}")
        return {}


def update_user_profile(db, username: str, display_name: str = None,
                         bio: str = None, avatar_url: str = None) -> bool:
    """Update editable profile-card fields for a user."""
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False
        if display_name is not None:
            user.display_name = display_name[:255] if display_name else None
        if bio is not None:
            user.bio = bio[:500] if bio else None
        if avatar_url is not None:
            # Only allow safe http/https URLs; reject anything else
            if avatar_url and not avatar_url.lower().startswith(('http://', 'https://')):
                avatar_url = ''
            user.avatar_url = avatar_url[:500] if avatar_url else None
        user.updated_at = datetime.utcnow()
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating user profile: {e}")
        db.rollback()
        return False


# ---------------------------------------------------------------------------
# In-app friendship helpers
# ---------------------------------------------------------------------------

def send_friend_request(db, from_username: str, to_username: str) -> tuple:
    """Send a friend request. Returns (success, message)."""
    if not db:
        return False, 'Database not available'
    try:
        sender = db.query(User).filter(User.username == from_username).first()
        target = db.query(User).filter(User.username == to_username).first()
        if not sender:
            return False, 'Sender not found'
        if not target:
            return False, f'User "{to_username}" not found'
        if sender.id == target.id:
            return False, 'Cannot send a friend request to yourself'
        # Check existing
        existing = db.query(UserFriendship).filter(
            ((UserFriendship.requester_id == sender.id) & (UserFriendship.addressee_id == target.id)) |
            ((UserFriendship.requester_id == target.id) & (UserFriendship.addressee_id == sender.id))
        ).first()
        if existing:
            if existing.status == 'accepted':
                return False, 'Already friends'
            if existing.status == 'pending':
                return False, 'Friend request already pending'
            # declined — re-request
            existing.status = 'pending'
            existing.requester_id = sender.id
            existing.addressee_id = target.id
            existing.updated_at = datetime.utcnow()
            db.commit()
            # Notify target
            _notify_friend_request(db, sender.username, target)
            return True, 'Friend request sent'
        friendship = UserFriendship(requester_id=sender.id, addressee_id=target.id, status='pending')
        db.add(friendship)
        db.commit()
        # Notify target
        _notify_friend_request(db, sender.username, target)
        return True, 'Friend request sent'
    except Exception as e:
        logger.error(f"Error sending friend request: {e}")
        db.rollback()
        return False, str(e)


def _notify_friend_request(db, sender_username: str, target_user) -> None:
    """Create a friend_request notification for target_user (best-effort)."""
    try:
        notif = Notification(
            user_id=target_user.id,
            type='friend_request',
            title='New Friend Request',
            message=f'{sender_username} sent you a friend request.',
        )
        db.add(notif)
        db.commit()
    except Exception as e:
        logger.warning(f"Could not create friend-request notification: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def respond_friend_request(db, username: str, requester_username: str, accept: bool) -> tuple:
    """Accept or decline a pending friend request."""
    if not db:
        return False, 'Database not available'
    try:
        user = db.query(User).filter(User.username == username).first()
        requester = db.query(User).filter(User.username == requester_username).first()
        if not user or not requester:
            return False, 'User not found'
        friendship = db.query(UserFriendship).filter(
            UserFriendship.requester_id == requester.id,
            UserFriendship.addressee_id == user.id,
            UserFriendship.status == 'pending',
        ).first()
        if not friendship:
            return False, 'No pending friend request found'
        friendship.status = 'accepted' if accept else 'declined'
        friendship.updated_at = datetime.utcnow()
        db.commit()
        # Notify the original requester when their request is accepted
        if accept:
            try:
                notif = Notification(
                    user_id=requester.id,
                    type='friend_request',
                    title='Friend Request Accepted',
                    message=f'{username} accepted your friend request. You are now friends!',
                )
                db.add(notif)
                db.commit()
            except Exception as e:
                logger.warning(f"Could not create acceptance notification: {e}")
                try:
                    db.rollback()
                except Exception:
                    pass
        return True, 'accepted' if accept else 'declined'
    except Exception as e:
        logger.error(f"Error responding to friend request: {e}")
        db.rollback()
        return False, str(e)


def get_app_friends(db, username: str) -> dict:
    """Return accepted friends, pending sent requests, and pending received requests."""
    if not db:
        return {'friends': [], 'sent': [], 'received': []}
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return {'friends': [], 'sent': [], 'received': []}

        friends, sent, received = [], [], []

        rows = db.query(UserFriendship).filter(
            (UserFriendship.requester_id == user.id) | (UserFriendship.addressee_id == user.id)
        ).all()

        for row in rows:
            is_requester = row.requester_id == user.id
            other_id = row.addressee_id if is_requester else row.requester_id
            other = db.query(User).filter(User.id == other_id).first()
            if not other:
                continue
            entry = {
                'username': other.username,
                'display_name': other.display_name or other.username,
                'avatar_url': other.avatar_url or '',
                'bio': other.bio or '',
            }
            if row.status == 'accepted':
                friends.append(entry)
            elif row.status == 'pending':
                if is_requester:
                    sent.append(entry)
                else:
                    received.append({**entry, 'requester': other.username})

        return {'friends': friends, 'sent': sent, 'received': received}
    except Exception as e:
        logger.error(f"Error getting app friends: {e}")
        return {'friends': [], 'sent': [], 'received': []}


def remove_app_friend(db, username: str, other_username: str) -> bool:
    """Remove a friendship (both directions)."""
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        other = db.query(User).filter(User.username == other_username).first()
        if not user or not other:
            return False
        db.query(UserFriendship).filter(
            ((UserFriendship.requester_id == user.id) & (UserFriendship.addressee_id == other.id)) |
            ((UserFriendship.requester_id == other.id) & (UserFriendship.addressee_id == user.id))
        ).delete(synchronize_session=False)
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error removing friend: {e}")
        db.rollback()
        return False


# ---------------------------------------------------------------------------
# AppSettings helpers
# ---------------------------------------------------------------------------

# Default settings shown in the admin panel.
_DEFAULT_SETTINGS = {
    'registration_open': ('true', 'Allow new users to register (true/false)'),
    'announcement': ('', 'Site-wide announcement shown to all logged-in users'),
    'max_pick_count': ('10', 'Maximum number of games a user can pick at once'),
    'default_platform': ('all', 'Default platform filter for game picker (all/steam/epic/gog)'),
    'leaderboard_public': ('true', 'Show leaderboard to all users (true/false)'),
    'chat_enabled': ('true', 'Enable the chat feature (true/false)'),
    'plugins_enabled': ('true', 'Enable the plugins system (true/false)'),
}


def get_app_settings(db) -> dict:
    """Return all app settings as a key→value dict.

    Missing keys are filled in from ``_DEFAULT_SETTINGS``.
    """
    if not db:
        return {k: v for k, (v, _) in _DEFAULT_SETTINGS.items()}
    try:
        rows = db.query(AppSettings).all()
        settings = {r.key: r.value for r in rows}
        # Fill missing defaults
        for key, (default_val, _) in _DEFAULT_SETTINGS.items():
            if key not in settings:
                settings[key] = default_val
        return settings
    except Exception as e:
        logger.error(f"Error getting app settings: {e}")
        return {k: v for k, (v, _) in _DEFAULT_SETTINGS.items()}


def get_app_setting(db, key: str, default=None) -> str:
    """Return a single app setting value by key."""
    settings = get_app_settings(db)
    return settings.get(key, default)


def set_app_settings(db, updates: dict, updated_by: str = None) -> bool:
    """Persist a dict of key→value updates.

    Creates missing rows; updates existing ones.
    """
    if not db:
        return False
    try:
        for key, value in updates.items():
            row = db.query(AppSettings).filter(AppSettings.key == key).first()
            description = _DEFAULT_SETTINGS.get(key, (None, None))[1]
            if row:
                row.value = str(value)
                row.updated_by = updated_by
                row.updated_at = datetime.utcnow()
            else:
                row = AppSettings(
                    key=key,
                    value=str(value),
                    description=description,
                    updated_by=updated_by,
                )
                db.add(row)
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error saving app settings: {e}")
        db.rollback()
        return False


def get_settings_with_meta(db) -> list:
    """Return settings as a list of dicts with key, value, and description."""
    current = get_app_settings(db)
    result = []
    for key, (default_val, description) in _DEFAULT_SETTINGS.items():
        result.append({
            'key': key,
            'value': current.get(key, default_val),
            'default': default_val,
            'description': description,
        })
    return result


# ---------------------------------------------------------------------------
# Ignored-games full-detail helper
# ---------------------------------------------------------------------------

def get_ignored_games_full(db, username: str) -> list:
    """Get full detail records for all games ignored by *username*.

    Unlike :func:`get_ignored_games`, which returns only a list of app-ID
    strings, this function returns a list of dicts that include
    ``app_id``, ``game_name``, ``reason``, and ``created_at``.

    Args:
        db:       SQLAlchemy session.
        username: Target username.

    Returns:
        List of dicts (may be empty).
    """
    if not db:
        return []
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return []
        return [
            {
                'app_id': ig.app_id,
                'game_name': ig.game_name,
                'reason': ig.reason,
                'created_at': ig.created_at.isoformat() if ig.created_at else None,
            }
            for ig in user.ignored_games
        ]
    except Exception as e:
        logger.error("Error getting full ignored games for %s: %s", username, e)
        return []


# ---------------------------------------------------------------------------
# Achievement hunt helpers
# ---------------------------------------------------------------------------

def sync_steam_achievements(
    db,
    username: str,
    steam_id: str,
    app_id: str,
    game_name: str,
    player_achievements: list,
    schema: dict,
) -> dict:
    """Upsert Steam achievement data for *username* from raw Steam API payloads.

    Args:
        db:                  SQLAlchemy session.
        username:            GAPI username.
        steam_id:            Steam 64-bit ID (informational only).
        app_id:              Steam app ID.
        game_name:           Human-readable game name.
        player_achievements: List of dicts from
                             ``ISteamUserStats/GetPlayerAchievements`` —
                             each must have at minimum ``apiname`` and
                             ``achieved`` (0/1) keys; may also include
                             ``unlocktime`` (epoch int).
        schema:              Dict mapping ``apiname`` → ``{name, description}``
                             from ``ISteamUserStats/GetSchemaForGame``.

    Returns:
        ``{'added': int, 'updated': int, 'total': int}`` counts.
    """
    if not db:
        return {'added': 0, 'updated': 0, 'total': 0}
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return {'added': 0, 'updated': 0, 'total': 0}

        app_id_str = str(app_id).strip()
        added = updated = 0
        import datetime as _dt

        for ach in player_achievements:
            api_name = ach.get('apiname', '').strip()
            if not api_name:
                continue
            achieved = bool(ach.get('achieved', 0))
            unlock_ts = ach.get('unlocktime', 0)
            unlock_time = None  # type: Optional[_dt.datetime]
            if unlock_ts:
                try:
                    unlock_time = _dt.datetime.utcfromtimestamp(int(unlock_ts))
                except (ValueError, OverflowError, OSError):
                    unlock_time = None

            meta = schema.get(api_name, {})
            disp_name = meta.get('name', api_name)
            description = meta.get('description', '')

            existing = (
                db.query(Achievement)
                .filter(
                    Achievement.user_id == user.id,
                    Achievement.app_id == app_id_str,
                    Achievement.achievement_id == api_name,
                )
                .first()
            )

            if existing:
                changed = False
                if existing.unlocked != achieved:
                    existing.unlocked = achieved
                    changed = True
                if unlock_time and existing.unlock_time != unlock_time:
                    existing.unlock_time = unlock_time
                    changed = True
                if disp_name and existing.achievement_name != disp_name:
                    existing.achievement_name = disp_name
                    changed = True
                if description and existing.achievement_description != description:
                    existing.achievement_description = description
                    changed = True
                if changed:
                    existing.updated_at = _dt.datetime.utcnow()
                    updated += 1
            else:
                db.add(Achievement(
                    user_id=user.id,
                    app_id=app_id_str,
                    game_name=game_name,
                    achievement_id=api_name,
                    achievement_name=disp_name,
                    achievement_description=description or None,
                    unlocked=achieved,
                    unlock_time=unlock_time,
                ))
                added += 1

        db.commit()
        # Total = existing rows after commit (includes newly added ones)
        total = (
            db.query(Achievement)
            .filter(Achievement.user_id == user.id, Achievement.app_id == app_id_str)
            .count()
        )
        return {'added': added, 'updated': updated, 'total': total}
    except Exception as e:
        logger.error("Error syncing Steam achievements for %s/%s: %s", username, app_id, e)
        db.rollback()
        return {'added': 0, 'updated': 0, 'total': 0}


def get_user_achievements_grouped(db, username: str) -> list:
    """Return achievements for *username* grouped by game.

    Args:
        db:       SQLAlchemy session.
        username: Target username.

    Returns:
        List of ``{'app_id', 'game_name', 'achievements': [...]}`` dicts.
    """
    if not db:
        return []
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return []

        grouped = {}
        for a in user.achievements:
            if a.app_id not in grouped:
                grouped[a.app_id] = {'app_id': a.app_id, 'game_name': a.game_name,
                                     'achievements': []}
            grouped[a.app_id]['achievements'].append({
                'achievement_id': a.achievement_id,
                'name': a.achievement_name,
                'description': a.achievement_description,
                'unlocked': a.unlocked,
                'unlock_time': a.unlock_time.isoformat() if a.unlock_time else None,
                'rarity': a.rarity,
            })
        return list(grouped.values())
    except Exception as e:
        logger.error("Error getting achievements for %s: %s", username, e)
        return []


def get_achievement_stats(db, username: str) -> dict:
    """Compute achievement statistics for *username*.

    Returns a dict with:
      - ``total_tracked``      – achievements tracked in the DB
      - ``total_unlocked``     – achievements marked as unlocked
      - ``completion_percent`` – unlocked / tracked × 100 (0 if none tracked)
      - ``rarest_achievement`` – the achievement with the lowest rarity value
        (i.e. fewest players have it), as a dict or ``None``
      - ``games``              – list of per-game summaries:
        ``{app_id, game_name, total, unlocked, completion_percent,
           rarest_rarity}``
    """
    if not db:
        return {}
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return {}

        all_ach = list(user.achievements)
        total = len(all_ach)
        unlocked = sum(1 for a in all_ach if a.unlocked)
        completion = round(unlocked / total * 100, 1) if total else 0.0

        # Rarest unlocked achievement (lowest rarity %)
        with_rarity = [a for a in all_ach if a.rarity is not None]
        rarest = None
        if with_rarity:
            candidate = min(with_rarity, key=lambda a: a.rarity)
            rarest = {
                'app_id': candidate.app_id,
                'game_name': candidate.game_name or '',
                'achievement_id': candidate.achievement_id,
                'name': candidate.achievement_name or '',
                'rarity': candidate.rarity,
                'unlocked': bool(candidate.unlocked),
            }

        # Per-game summary
        grouped: dict = {}
        for a in all_ach:
            key = a.app_id
            if key not in grouped:
                grouped[key] = {
                    'app_id': key,
                    'game_name': a.game_name or '',
                    'total': 0,
                    'unlocked': 0,
                    'rarities': [],
                }
            grouped[key]['total'] += 1
            if a.unlocked:
                grouped[key]['unlocked'] += 1
            if a.rarity is not None:
                grouped[key]['rarities'].append(a.rarity)

        games = []
        for g in sorted(grouped.values(), key=lambda x: x['game_name'].lower()):
            pct = round(g['unlocked'] / g['total'] * 100, 1) if g['total'] else 0.0
            min_rarity = min(g['rarities']) if g['rarities'] else None
            games.append({
                'app_id': g['app_id'],
                'game_name': g['game_name'],
                'total': g['total'],
                'unlocked': g['unlocked'],
                'completion_percent': pct,
                'rarest_rarity': min_rarity,
            })

        return {
            'total_tracked': total,
            'total_unlocked': unlocked,
            'completion_percent': completion,
            'rarest_achievement': rarest,
            'games': games,
        }
    except Exception as e:
        logger.error("Error computing achievement stats for %s: %s", username, e)
        return {}


def get_games_with_rare_achievements(
    db, username: str,
    max_rarity: float = 100.0,
    min_rarity: float = 0.0,
) -> list:
    """Return app_ids that have at least one *unlocked=False* achievement whose
    rarity falls within ``[min_rarity, max_rarity]``.

    This is used by the game-picker rarity filter to surface games where the
    user still has rare (or semi-rare) achievements left to earn.

    Args:
        db:          SQLAlchemy session.
        username:    Target username.
        max_rarity:  Inclusive upper bound for rarity % (default 100).
        min_rarity:  Inclusive lower bound for rarity % (default 0).

    Returns:
        List of app_id strings.
    """
    if not db:
        return []
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return []
        app_ids = set()
        for a in user.achievements:
            if a.unlocked:
                continue
            if a.rarity is None:
                continue
            if min_rarity <= a.rarity <= max_rarity:
                app_ids.add(str(a.app_id))
        return list(app_ids)
    except Exception as e:
        logger.error("Error getting rare-achievement games for %s: %s", username, e)
        return []


def get_achievement_stats_by_platform(db, username: str) -> list:
    """Return achievement statistics grouped by platform for *username*.

    Joins ``Achievement`` rows with ``GameLibraryCache`` to resolve the
    platform for each game.  Games not found in the library cache default
    to ``'steam'``.

    Returns:
        List of ``{'platform', 'total_tracked', 'total_unlocked',
        'completion_percent', 'game_count'}`` dicts sorted by platform name.
    """
    if not db:
        return []
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return []

        # Build {app_id -> platform} map from cached library
        library_map: dict = {}
        for g in user.game_libraries:
            if g.app_id and g.platform:
                library_map[str(g.app_id)] = g.platform.lower()

        grouped: dict = {}
        for a in user.achievements:
            platform = library_map.get(str(a.app_id), 'steam')
            if platform not in grouped:
                grouped[platform] = {
                    'platform': platform,
                    'total_tracked': 0,
                    'total_unlocked': 0,
                    'app_ids': set(),
                }
            grouped[platform]['total_tracked'] += 1
            if a.unlocked:
                grouped[platform]['total_unlocked'] += 1
            grouped[platform]['app_ids'].add(str(a.app_id))

        result = []
        for entry in sorted(grouped.values(), key=lambda x: x['platform']):
            total = entry['total_tracked']
            unlocked = entry['total_unlocked']
            result.append({
                'platform': entry['platform'],
                'total_tracked': total,
                'total_unlocked': unlocked,
                'completion_percent': round(unlocked / total * 100, 1) if total else 0.0,
                'game_count': len(entry['app_ids']),
            })
        return result
    except Exception as e:
        logger.error("Error computing platform achievement stats for %s: %s", username, e)
        return []


# ---------------------------------------------------------------------------
# Achievement challenge helpers
# ---------------------------------------------------------------------------

def _challenge_to_dict(challenge: 'AchievementChallenge') -> dict:
    """Serialise an AchievementChallenge to a plain dict."""
    return {
        'id': challenge.challenge_id,
        'title': challenge.title,
        'app_id': challenge.app_id,
        'game_name': challenge.game_name,
        'target_achievement_ids': (
            [a.strip() for a in challenge.target_achievement_ids.split(',')
             if a.strip()]
            if challenge.target_achievement_ids else []
        ),
        'status': challenge.status,
        'created_by': challenge.creator.username if challenge.creator else None,
        'winner': challenge.winner.username if challenge.winner else None,
        'starts_at': challenge.starts_at.isoformat() if challenge.starts_at else None,
        'ends_at': challenge.ends_at.isoformat() if challenge.ends_at else None,
        'created_at': challenge.created_at.isoformat() if challenge.created_at else None,
        'participants': [
            {
                'username': p.user.username if p.user else None,
                'unlocked_count': p.unlocked_count,
                'completed': bool(p.completed),
                'joined_at': p.joined_at.isoformat() if p.joined_at else None,
                'completed_at': p.completed_at.isoformat() if p.completed_at else None,
            }
            for p in challenge.participants
        ],
    }


def create_achievement_challenge(
    db,
    creator_username: str,
    title: str,
    app_id: str,
    game_name: str,
    target_achievement_ids: list = None,
    starts_at: str = '',
    ends_at: str = '',
) -> dict:
    """Create a new multiplayer achievement challenge.

    The creator is automatically added as the first participant.

    Args:
        db:                      SQLAlchemy session.
        creator_username:        Username of the user creating the challenge.
        title:                   Short challenge title.
        app_id:                  Steam/platform app ID.
        game_name:               Human-readable game name.
        target_achievement_ids:  List of achievement IDs to complete (empty = all).
        starts_at:               ISO date-time string for challenge start (optional).
        ends_at:                 ISO date-time string for challenge end (optional).

    Returns:
        Challenge dict on success, empty dict on failure.
    """
    if not db:
        return {}
    import uuid as _uuid
    try:
        user = db.query(User).filter(User.username == creator_username).first()
        if not user:
            return {}

        def _parse_dt(s: str):
            if not s:
                return None
            import datetime as _dt
            for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d'):
                try:
                    return _dt.datetime.strptime(s.strip(), fmt)
                except ValueError:
                    pass
            return None

        challenge_id = str(_uuid.uuid4())[:12]
        challenge = AchievementChallenge(
            challenge_id=challenge_id,
            title=title.strip(),
            app_id=str(app_id).strip(),
            game_name=game_name.strip(),
            target_achievement_ids=','.join(target_achievement_ids) if target_achievement_ids else None,
            status='open',
            created_by=user.id,
            starts_at=_parse_dt(starts_at),
            ends_at=_parse_dt(ends_at),
        )
        db.add(challenge)
        db.flush()  # get challenge.id

        # Add creator as first participant
        participant = ChallengeParticipant(
            challenge_id=challenge.id,
            user_id=user.id,
        )
        db.add(participant)
        db.commit()
        db.refresh(challenge)
        return _challenge_to_dict(challenge)
    except Exception as e:
        logger.error("Error creating achievement challenge: %s", e)
        db.rollback()
        return {}


def get_achievement_challenges(db, username: str) -> list:
    """Return all challenges where *username* is creator or participant.

    Returns:
        List of challenge dicts sorted by ``created_at`` descending.
    """
    if not db:
        return []
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return []
        # Challenges created by user
        created = db.query(AchievementChallenge).filter(
            AchievementChallenge.created_by == user.id
        ).all()
        # Challenges user participates in (but didn't create)
        participating = (
            db.query(AchievementChallenge)
            .join(ChallengeParticipant,
                  ChallengeParticipant.challenge_id == AchievementChallenge.id)
            .filter(
                ChallengeParticipant.user_id == user.id,
                AchievementChallenge.created_by != user.id,
            )
            .all()
        )
        all_challenges = {c.id: c for c in created + participating}
        return sorted(
            [_challenge_to_dict(c) for c in all_challenges.values()],
            key=lambda c: c['created_at'] or '',
            reverse=True,
        )
    except Exception as e:
        logger.error("Error getting challenges for %s: %s", username, e)
        return []


def get_achievement_challenge(db, challenge_id: str) -> dict:
    """Return a single challenge dict by *challenge_id*, or empty dict if not found."""
    if not db:
        return {}
    try:
        c = db.query(AchievementChallenge).filter(
            AchievementChallenge.challenge_id == challenge_id
        ).first()
        return _challenge_to_dict(c) if c else {}
    except Exception as e:
        logger.error("Error getting challenge %s: %s", challenge_id, e)
        return {}


def join_achievement_challenge(db, challenge_id: str, username: str) -> dict:
    """Add *username* as a participant in *challenge_id*.

    Returns the updated challenge dict, or empty dict on failure.
    No-ops if the user is already a participant.
    """
    if not db:
        return {}
    try:
        user = db.query(User).filter(User.username == username).first()
        challenge = db.query(AchievementChallenge).filter(
            AchievementChallenge.challenge_id == challenge_id
        ).first()
        if not user or not challenge:
            return {}
        already = db.query(ChallengeParticipant).filter(
            ChallengeParticipant.challenge_id == challenge.id,
            ChallengeParticipant.user_id == user.id,
        ).first()
        if not already:
            db.add(ChallengeParticipant(challenge_id=challenge.id, user_id=user.id))
            if challenge.status == 'open':
                challenge.status = 'in_progress'
            db.commit()
            db.refresh(challenge)
        return _challenge_to_dict(challenge)
    except Exception as e:
        logger.error("Error joining challenge %s: %s", challenge_id, e)
        db.rollback()
        return {}


def record_challenge_unlock(
    db, challenge_id: str, username: str, unlocked_count: int
) -> dict:
    """Update the participant's unlocked count and check for completion.

    Marks the challenge as completed + sets the winner when any participant
    reaches the target achievement count (or unlocked_count >= total targets).

    Returns the updated challenge dict.
    """
    if not db:
        return {}
    import datetime as _dt
    try:
        user = db.query(User).filter(User.username == username).first()
        challenge = db.query(AchievementChallenge).filter(
            AchievementChallenge.challenge_id == challenge_id
        ).first()
        if not user or not challenge:
            return {}
        participant = db.query(ChallengeParticipant).filter(
            ChallengeParticipant.challenge_id == challenge.id,
            ChallengeParticipant.user_id == user.id,
        ).first()
        if not participant:
            return {}
        participant.unlocked_count = unlocked_count

        # Determine target count
        target = 0
        if challenge.target_achievement_ids:
            target = len([a for a in challenge.target_achievement_ids.split(',') if a.strip()])

        if target > 0 and unlocked_count >= target and not participant.completed:
            participant.completed = True
            participant.completed_at = _dt.datetime.utcnow()
            # First to complete wins
            if challenge.status != 'completed':
                challenge.status = 'completed'
                challenge.winner_user_id = user.id

        db.commit()
        db.refresh(challenge)
        return _challenge_to_dict(challenge)
    except Exception as e:
        logger.error("Error recording challenge unlock for %s: %s", challenge_id, e)
        db.rollback()
        return {}


def cancel_achievement_challenge(db, challenge_id: str, requester_username: str) -> bool:
    """Cancel a challenge. Only the creator may cancel.

    Returns True if cancelled, False otherwise.
    """
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == requester_username).first()
        challenge = db.query(AchievementChallenge).filter(
            AchievementChallenge.challenge_id == challenge_id
        ).first()
        if not user or not challenge:
            return False
        if challenge.created_by != user.id:
            return False
        challenge.status = 'cancelled'
        db.commit()
        return True
    except Exception as e:
        logger.error("Error cancelling challenge %s: %s", challenge_id, e)
        db.rollback()
        return False


def start_achievement_hunt(db, username: str, app_id: int, game_name: str,
                           difficulty: str = 'medium',
                           target_achievements: int = 0) -> dict:
    """Create a new achievement-hunt session for *username*.

    Args:
        db:                   SQLAlchemy session.
        username:             Target username.
        app_id:               Integer Steam app ID.
        game_name:            Human-readable game name.
        difficulty:           One of ``'easy'``, ``'medium'``, ``'hard'``,
                              ``'extreme'``.
        target_achievements:  Total number of achievements to unlock (0 = all).

    Returns:
        Dict with hunt details on success, empty dict on failure.
    """
    if not db:
        return {}
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return {}

        hunt = AchievementHunt(
            user_id=user.id,
            app_id=app_id,
            game_name=game_name,
            difficulty=difficulty,
            target_achievements=target_achievements,
        )
        db.add(hunt)
        db.commit()
        return {
            'hunt_id': hunt.id,
            'app_id': hunt.app_id,
            'game_name': hunt.game_name,
            'difficulty': hunt.difficulty,
            'target_achievements': hunt.target_achievements,
            'unlocked_achievements': hunt.unlocked_achievements,
            'progress_percent': hunt.progress_percent,
            'status': hunt.status,
            'started_at': hunt.started_at.isoformat(),
        }
    except Exception as e:
        logger.error("Error starting achievement hunt for %s: %s", username, e)
        db.rollback()
        return {}


def update_achievement_hunt(db, hunt_id, unlocked_achievements=None,
                            status: str = None) -> dict:
    """Update progress or status of an existing achievement hunt.

    Args:
        db:                    SQLAlchemy session.
        hunt_id:               Primary-key ID of the hunt record.
        unlocked_achievements: New unlocked count (``None`` → unchanged).
        status:                New status string (``None`` → unchanged).

    Returns:
        Dict with updated hunt details on success, empty dict if not found or
        on error.
    """
    if not db:
        return {}
    try:
        hunt = db.query(AchievementHunt).filter(
            AchievementHunt.id == hunt_id).first()
        if not hunt:
            return {}

        if unlocked_achievements is not None:
            hunt.unlocked_achievements = unlocked_achievements
            if hunt.target_achievements > 0:
                hunt.progress_percent = (
                    unlocked_achievements / hunt.target_achievements * 100)

        if status:
            hunt.status = status
            if status == 'completed':
                hunt.completed_at = datetime.now(timezone.utc)

        hunt.updated_at = datetime.now(timezone.utc)
        db.commit()
        return {
            'hunt_id': hunt.id,
            'app_id': hunt.app_id,
            'game_name': hunt.game_name,
            'difficulty': hunt.difficulty,
            'target_achievements': hunt.target_achievements,
            'unlocked_achievements': hunt.unlocked_achievements,
            'progress_percent': hunt.progress_percent,
            'status': hunt.status,
            'started_at': hunt.started_at.isoformat(),
            'completed_at': (hunt.completed_at.isoformat()
                             if hunt.completed_at else None),
        }
    except Exception as e:
        logger.error("Error updating achievement hunt %s: %s", hunt_id, e)
        db.rollback()
        return {}


# ---------------------------------------------------------------------------
# User platform-IDs helper
# ---------------------------------------------------------------------------

def get_user_platform_ids(db, username: str) -> dict:
    """Return the platform IDs stored for *username*.

    Args:
        db:       SQLAlchemy session.
        username: Target username.

    Returns:
        Dict with ``steam_id``, ``epic_id``, and ``gog_id`` keys.  Any
        missing value is returned as an empty string.  Returns an empty
        dict when the user is not found or on error.
    """
    if not db:
        return {}
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return {}
        return {
            'steam_id': user.steam_id or '',
            'epic_id': user.epic_id or '',
            'gog_id': user.gog_id or '',
        }
    except Exception as e:
        logger.error("Error getting platform IDs for %s: %s", username, e)
        return {}


# ---------------------------------------------------------------------------
# Game-platform and stale-details helpers
# ---------------------------------------------------------------------------

def get_game_platform_for_user(db, username: str, app_id) -> str:
    """Return the platform stored in the library cache for *app_id*.

    Args:
        db:       SQLAlchemy session.
        username: Target username.
        app_id:   App ID to look up (coerced to string for the query).

    Returns:
        Platform string (e.g. ``'steam'``, ``'epic'``).  Falls back to
        ``'steam'`` when no matching entry is found or on error.
    """
    if not db:
        return 'steam'
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return 'steam'
        entry = db.query(GameLibraryCache).filter(
            GameLibraryCache.user_id == user.id,
            GameLibraryCache.app_id == str(app_id),
        ).first()
        return (entry.platform or 'steam') if entry else 'steam'
    except Exception as e:
        logger.error("Error getting game platform for user %s / app %s: %s",
                     username, app_id, e)
        return 'steam'


def get_game_details_stale(db, app_id, platform: str = 'steam') -> 'dict | None':
    """Return the last cached game-details entry regardless of age.

    Unlike :func:`get_game_details_cache` (which enforces a freshness
    limit), this function always returns the most-recent entry if one
    exists.  Useful as a last-resort fallback when no API data is
    available.

    Args:
        db:       SQLAlchemy session.
        app_id:   Game app ID.
        platform: Platform name.

    Returns:
        Parsed details dict, or ``None`` when no entry exists or on error.
    """
    if not db:
        return None
    try:
        import json as _json
        entry = db.query(GameDetailsCache).filter(
            GameDetailsCache.app_id == str(app_id),
            GameDetailsCache.platform == platform,
        ).first()
        if entry:
            return _json.loads(entry.details_json)
        return None
    except Exception as e:
        logger.error("Error getting stale game details for app %s: %s", app_id, e)
        return None


# ---------------------------------------------------------------------------
# User presence helpers
# ---------------------------------------------------------------------------

def update_user_presence(db, username: str) -> bool:
    """Update the ``last_seen`` timestamp for *username* to now.

    Returns ``True`` on success, ``False`` otherwise.
    """
    if not db:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False
        user.last_seen = datetime.utcnow()
        db.commit()
        return True
    except Exception as e:
        logger.error("Error updating presence for %s: %s", username, e)
        db.rollback()
        return False


def get_online_users(db, threshold_minutes: int = 5) -> list:
    """Return a list of users who were active within *threshold_minutes*.

    Each entry is a dict with ``username``, ``display_name``, ``avatar_url``,
    ``steam_id``, ``epic_id``, and ``gog_id``.
    """
    if not db:
        return []
    try:
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(minutes=threshold_minutes)
        users = db.query(User).filter(User.last_seen >= cutoff).all()
        return [
            {
                'username': u.username,
                'display_name': u.display_name or u.username,
                'avatar_url': u.avatar_url or '',
                'steam_id': u.steam_id or '',
                'epic_id': u.epic_id or '',
                'gog_id': u.gog_id or '',
            }
            for u in users
        ]
    except Exception as e:
        logger.error("Error getting online users: %s", e)
        return []


def get_app_friends_with_platforms(db, username: str) -> dict:
    """Return accepted friends for *username*, including platform IDs.

    Extends :func:`get_app_friends` by adding ``steam_id``, ``epic_id``,
    ``gog_id``, and ``is_online`` (active within 5 minutes) to each friend
    entry in the ``'friends'`` list.  The ``'sent'`` and ``'received'``
    lists are returned as-is from :func:`get_app_friends`.
    """
    result = get_app_friends(db, username)
    if not db:
        return result
    try:
        from datetime import timedelta
        online_cutoff = datetime.utcnow() - timedelta(minutes=5)
        enriched = []
        for entry in result.get('friends', []):
            friend_user = db.query(User).filter(
                User.username == entry['username']
            ).first()
            if friend_user:
                entry = dict(entry)
                entry['steam_id'] = friend_user.steam_id or ''
                entry['epic_id'] = friend_user.epic_id or ''
                entry['gog_id'] = friend_user.gog_id or ''
                entry['is_online'] = bool(
                    friend_user.last_seen and friend_user.last_seen >= online_cutoff
                )
            enriched.append(entry)
        result['friends'] = enriched
    except Exception as e:
        logger.error("Error enriching friends with platform info: %s", e)
    return result


# ============================================================================
# Phase 6: Advanced Features DB Models
# ============================================================================

class ShopItem(Base):
    """Shop items available for purchase"""
    __tablename__ = "shop_items"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, index=True)
    icon = Column(String(10))  # emoji
    description = Column(String(500))
    price = Column(Integer)  # in XP or coins
    currency = Column(String(20))  # 'xp' or 'coins'
    premium = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserInventory(Base):
    """User's purchased items (cosmetics, themes, etc)"""
    __tablename__ = "user_inventory"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    item_id = Column(Integer, ForeignKey("shop_items.id"), index=True)
    purchased_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (UniqueConstraint('user_id', 'item_id', name='unique_user_item'),)
    
    user = relationship("User")
    item = relationship("ShopItem")


class StreamVOD(Base):
    """Video On Demand (VOD) from streams"""
    __tablename__ = "stream_vods"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    title = Column(String(255))
    duration = Column(String(20))  # "HH:MM:SS"
    views = Column(Integer, default=0)
    vod_url = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User")


class TradeOffer(Base):
    """Player-to-player trading system"""
    __tablename__ = "trade_offers"
    
    id = Column(Integer, primary_key=True)
    from_user_id = Column(Integer, ForeignKey("users.id"), index=True)
    to_user_id = Column(Integer, ForeignKey("users.id"), index=True)
    offer_description = Column(Text)  # What's being offered
    status = Column(String(20), default='pending')  # pending, accepted, declined
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Team(Base):
    """Player teams/clans for group matches"""
    __tablename__ = "teams"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, index=True)
    leader_id = Column(Integer, ForeignKey("users.id"), index=True)
    description = Column(String(500))
    max_members = Column(Integer, default=5)
    win_rate = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    leader = relationship("User")


class TeamMembership(Base):
    """User membership in teams"""
    __tablename__ = "team_memberships"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), index=True)
    role = Column(String(20), default='member')  # leader, officer, member
    joined_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (UniqueConstraint('user_id', 'team_id', name='unique_user_team'),)
    
    user = relationship("User")
    team = relationship("Team")


class RankedRating(Base):
    """User's ranked tier and rating points"""
    __tablename__ = "ranked_ratings"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)
    tier = Column(String(20))  # bronze, silver, gold, diamond, master
    tier_level = Column(Integer, default=1)  # I, II, III, IV
    rating_points = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User")


class AntiCheatLog(Base):
    """Anti-cheat integrity logs for each pick"""
    __tablename__ = "anticheat_logs"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    session_id = Column(String(255), index=True)  # reference to game session
    game_picked = Column(String(255))
    accuracy_variance = Column(Float)  # percentage deviation from average
    response_time_ms = Column(Integer)  # milliseconds
    is_flagged = Column(Boolean, default=False)
    flag_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User")


class UserCosmetics(Base):
    """User's active cosmetic theme and title"""
    __tablename__ = "user_cosmetics"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)
    active_theme = Column(String(50))  # theme name
    active_title = Column(String(100))  # title/badge name
    profile_color = Column(String(7))  # hex color
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User")


class GameReview(Base):
    """User-generated game reviews"""
    __tablename__ = "game_reviews"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    game_name = Column(String(255), index=True)
    rating = Column(Integer)  # 1-5 stars
    review_text = Column(Text)
    helpful_votes = Column(Integer, default=0)
    unhelpful_votes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User")


class AIRecommendationCache(Base):
    """Cached AI recommendations for users"""
    __tablename__ = "ai_recommendations"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)
    game_name = Column(String(255), index=True)
    match_score = Column(Integer)  # 0-100
    reason = Column(String(255))
    recommended_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User")

# ==================== PHASE 7: Advanced Features ====================

class BattlePass(Base):
    """Seasonal battle pass system"""
    __tablename__ = "battle_passes"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, index=True)
    season = Column(Integer, index=True)
    duration_days = Column(Integer)
    max_level = Column(Integer, default=100)
    free_tier_reward = Column(String(255))
    premium_price = Column(Integer, default=999)  # In points
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserBattlePass(Base):
    """User progress in battle pass"""
    __tablename__ = "user_battle_passes"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    battle_pass_id = Column(Integer, ForeignKey("battle_passes.id"))
    current_level = Column(Integer, default=1)
    experience = Column(Integer, default=0)
    has_premium = Column(Boolean, default=False)
    purchased_at = Column(DateTime)
    
    user = relationship("User")
    battle_pass = relationship("BattlePass")
    UniqueConstraint('user_id', 'battle_pass_id', name='uq_user_battle_pass')


class Tournament(Base):
    """Tournament brackets and management"""
    __tablename__ = "tournaments"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, index=True)
    game = Column(String(255), index=True)
    tournament_type = Column(String(50), default='bracket')  # bracket, round-robin, swiss
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    max_participants = Column(Integer, default=64)
    entry_fee = Column(Integer, default=0)
    total_prize_pool = Column(Integer, default=0)
    status = Column(String(50), default='registration')  # registration, active, completed
    organizer_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    organizer = relationship("User")


class TournamentParticipant(Base):
    """Tournament participants"""
    __tablename__ = "tournament_participants"
    
    id = Column(Integer, primary_key=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    bracket_position = Column(Integer)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    prize_earned = Column(Integer, default=0)
    registered_at = Column(DateTime, default=datetime.utcnow)
    
    tournament = relationship("Tournament")
    user = relationship("User")
    UniqueConstraint('tournament_id', 'user_id', name='uq_tournament_user')


class ContentCreatorPass(Base):
    """Creator program membership"""
    __tablename__ = "creator_passes"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)
    tier = Column(String(50), default='bronze')  # bronze, silver, gold, platinum
    total_followers = Column(Integer, default=0)
    total_views = Column(Integer, default=0)
    revenue_share_percent = Column(Integer, default=20)
    verification_status = Column(String(50), default='pending')
    joined_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User")


class ReferralCode(Base):
    """Referral system and rewards"""
    __tablename__ = "referral_codes"
    
    id = Column(Integer, primary_key=True)
    referrer_id = Column(Integer, ForeignKey("users.id"), index=True)
    code = Column(String(32), unique=True, index=True)
    reward_points = Column(Integer, default=500)
    uses_remaining = Column(Integer, default=-1)  # -1 = unlimited
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    referrer = relationship("User")


class ReferralUse(Base):
    """Tracking of referral code uses"""
    __tablename__ = "referral_uses"
    
    id = Column(Integer, primary_key=True)
    referral_code_id = Column(Integer, ForeignKey("referral_codes.id"))
    referrer_id = Column(Integer, ForeignKey("users.id"))
    referred_user_id = Column(Integer, ForeignKey("users.id"))
    reward_claimed = Column(Boolean, default=False)
    used_at = Column(DateTime, default=datetime.utcnow)
    
    referral_code = relationship("ReferralCode")
    referrer = relationship("User", foreign_keys=[referrer_id])
    referred_user = relationship("User", foreign_keys=[referred_user_id])


class SeasonalEvent(Base):
    """Limited-time seasonal events"""
    __tablename__ = "seasonal_events"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, index=True)
    description = Column(Text)
    season = Column(String(50), index=True)  # spring, summer, fall, winter
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    reward_type = Column(String(50), default='cosmetics')  # cosmetics, points, currency
    max_reward_quantity = Column(Integer)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class EventParticipation(Base):
    """User participation in seasonal events"""
    __tablename__ = "event_participations"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    event_id = Column(Integer, ForeignKey("seasonal_events.id"))
    progress = Column(Integer, default=0)
    completed = Column(Boolean, default=False)
    reward_claimed = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User")
    event = relationship("SeasonalEvent")
    UniqueConstraint('user_id', 'event_id', name='uq_user_event')


class Guild(Base):
    """Guild/clan organization and economy"""
    __tablename__ = "guilds"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, index=True)
    leader_id = Column(Integer, ForeignKey("users.id"))
    description = Column(Text)
    max_members = Column(Integer, default=50)
    member_count = Column(Integer, default=1)
    guild_level = Column(Integer, default=1)
    treasury_balance = Column(Integer, default=0)
    tax_rate = Column(Integer, default=10)  # Percentage on member transactions
    is_recruiting = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    leader = relationship("User")


class GuildMember(Base):
    """Guild membership"""
    __tablename__ = "guild_members"
    
    id = Column(Integer, primary_key=True)
    guild_id = Column(Integer, ForeignKey("guilds.id"))
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    role = Column(String(50), default='member')  # leader, officer, member
    contribution_points = Column(Integer, default=0)
    joined_at = Column(DateTime, default=datetime.utcnow)
    
    guild = relationship("Guild")
    user = relationship("User")
    UniqueConstraint('guild_id', 'user_id', name='uq_guild_user')


class ProgressionPath(Base):
    """Career progression paths and roles"""
    __tablename__ = "progression_paths"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, index=True)
    description = Column(Text)
    min_level = Column(Integer, default=1)
    total_steps = Column(Integer, default=10)
    rewards_per_step = Column(String(255))  # JSON: {cosmetics, points, titles}
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserProgressionPath(Base):
    """User progress on a path"""
    __tablename__ = "user_progression_paths"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    path_id = Column(Integer, ForeignKey("progression_paths.id"))
    current_step = Column(Integer, default=1)
    completed_steps = Column(Integer, default=0)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    
    user = relationship("User")
    path = relationship("ProgressionPath")
    UniqueConstraint('user_id', 'path_id', name='uq_user_path')


class TradingMarket(Base):
    """Player-to-player trading marketplace"""
    __tablename__ = "trading_markets"
    
    id = Column(Integer, primary_key=True)
    seller_id = Column(Integer, ForeignKey("users.id"), index=True)
    item_name = Column(String(255), index=True)
    item_description = Column(Text)
    asking_price = Column(Integer)
    item_rarity = Column(String(50), default='common')  # common, rare, epic, legendary
    status = Column(String(50), default='active')  # active, sold, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    sold_at = Column(DateTime)
    
    seller = relationship("User")


class MarketOffer(Base):
    """Offers on marketplace items"""
    __tablename__ = "market_offers"
    
    id = Column(Integer, primary_key=True)
    market_item_id = Column(Integer, ForeignKey("trading_markets.id"))
    buyer_id = Column(Integer, ForeignKey("users.id"))
    offered_price = Column(Integer)
    status = Column(String(50), default='pending')  # pending, accepted, rejected
    created_at = Column(DateTime, default=datetime.utcnow)
    
    item = relationship("TradingMarket")
    buyer = relationship("User")


class CosmeticCollection(Base):
    """Cosmetic item collections and albums"""
    __tablename__ = "cosmetic_collections"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    collection_name = Column(String(255))
    cosmetic_type = Column(String(50), index=True)  # theme, title, banner, frame
    owned_count = Column(Integer, default=0)
    total_rarity_points = Column(Integer, default=0)
    collection_completion_percent = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User")

# ---------------------------------------------------------------------------
# Database Optimization & Maintenance helpers  (Tier 3, item 10)
# ---------------------------------------------------------------------------

def get_table_stats(db) -> list:
    """Return row counts and (where available) on-disk sizes for every table.

    Returns a list of dicts sorted by row count descending:
      ``table``     – table name
      ``rows``      – approximate row count (exact for SQLite, estimate for Postgres)
      ``size_bytes``– on-disk size in bytes (PostgreSQL only; ``None`` for SQLite)

    If *db* is None or an error occurs, returns an empty list.
    """
    if not db or not engine:
        return []
    try:
        from sqlalchemy import inspect as _inspect, text as _text
        from sqlalchemy.sql import quoted_name
        inspector = _inspect(engine)
        table_names = inspector.get_table_names()
        dialect = engine.dialect.name
        stats = []
        for tbl in table_names:
            # tbl comes from the inspector so it is always a real table name;
            # we still quote it to guard against unusual names.
            safe_tbl = str(quoted_name(tbl, quote=True))
            try:
                count_row = db.execute(_text(f"SELECT COUNT(*) FROM {safe_tbl}")).fetchone()
                row_count = int(count_row[0]) if count_row else 0
            except Exception:
                row_count = 0
            size_bytes = None
            if dialect == 'postgresql':
                try:
                    size_row = db.execute(
                        _text("SELECT pg_total_relation_size(:tbl)"),
                        {'tbl': tbl},
                    ).fetchone()
                    size_bytes = int(size_row[0]) if size_row else None
                except Exception:
                    pass
            stats.append({'table': tbl, 'rows': row_count, 'size_bytes': size_bytes})
        stats.sort(key=lambda r: r['rows'], reverse=True)
        return stats
    except Exception as e:
        logger.error(f"get_table_stats error: {e}")
        return []


def get_db_size_bytes() -> int:
    """Return total on-disk size of the database in bytes.

    For SQLite, reads ``os.path.getsize`` on the database file.
    For PostgreSQL, queries ``pg_database_size``.
    Returns 0 on error or when the database is not available.
    """
    if not engine:
        return 0
    try:
        dialect = engine.dialect.name
        if dialect == 'sqlite':
            db_url = str(engine.url)
            # sqlite:////path/to/db.sqlite  →  /path/to/db.sqlite
            path = db_url.replace('sqlite:///', '').replace('sqlite://', '')
            if path and os.path.exists(path):
                return os.path.getsize(path)
            return 0
        elif dialect == 'postgresql':
            from sqlalchemy import text as _text
            with engine.connect() as conn:
                row = conn.execute(_text("SELECT pg_database_size(current_database())")).fetchone()
                return int(row[0]) if row else 0
        return 0
    except Exception as e:
        logger.error(f"get_db_size_bytes error: {e}")
        return 0


def apply_indexes(db, dry_run: bool = True) -> dict:
    """Create recommended database indexes that do not yet exist.

    Uses ``IndexAnalyzer.analyze_query_bottlenecks()`` from the *performance*
    module to obtain the index DDL statements, then for each statement checks
    whether the index already exists and, if *dry_run* is ``False``, executes
    ``CREATE INDEX … IF NOT EXISTS …`` (or the equivalent).

    Returns a dict:
      ``applied``   – list of DDL statements executed
      ``skipped``   – list of DDL statements where the index already existed
      ``errors``    – list of ``{sql, error}`` dicts for any failed statements
      ``dry_run``   – reflects the *dry_run* parameter
    """
    result = {'applied': [], 'skipped': [], 'errors': [], 'dry_run': dry_run}
    if not db or not engine:
        return result
    try:
        from performance import IndexAnalyzer
        from sqlalchemy import inspect as _inspect, text as _text
        suggestions = IndexAnalyzer.analyze_query_bottlenecks()
        inspector = _inspect(engine)
        # Build set of existing index names (lower-cased) per table
        existing: dict = {}
        for tbl in inspector.get_table_names():
            for idx in inspector.get_indexes(tbl):
                existing[idx['name'].lower()] = True
        for ddl in suggestions:
            # Extract the index name from "CREATE INDEX idx_xxx ON ..."
            parts = ddl.split()
            idx_name = ''
            if len(parts) >= 3:
                idx_name = parts[2].lower()
            if idx_name and idx_name in existing:
                result['skipped'].append(ddl)
                continue
            if dry_run:
                result['applied'].append(ddl)
            else:
                try:
                    # Convert to IF NOT EXISTS form for safety
                    safe_ddl = ddl.replace(
                        'CREATE INDEX ', 'CREATE INDEX IF NOT EXISTS ', 1
                    ).replace(
                        'CREATE UNIQUE INDEX ', 'CREATE UNIQUE INDEX IF NOT EXISTS ', 1
                    )
                    with engine.begin() as conn:
                        conn.execute(_text(safe_ddl.rstrip(';')))
                    result['applied'].append(ddl)
                    logger.info(f"Created index: {idx_name}")
                except Exception as e:
                    result['errors'].append({'sql': ddl, 'error': str(e)})
    except Exception as e:
        logger.error(f"apply_indexes error: {e}")
    return result


def archive_old_picks(db, days: int = 365) -> dict:
    """Delete pick/session records older than *days* days.

    Removes rows from:
      - ``picks``        – all rows whose ``created_at`` is before the cutoff date
      - ``live_sessions``– rows whose ``created_at`` is before the cutoff date
        **and** whose ``status`` is ``'completed'`` or ``'ended'``

    Returns a dict:
      ``deleted_picks``    – number of pick rows removed
      ``deleted_sessions`` – number of live_session rows removed
      ``cutoff_date``      – ISO 8601 timestamp used as cutoff
      ``days``             – reflects the *days* parameter
    """
    result = {'deleted_picks': 0, 'deleted_sessions': 0,
              'cutoff_date': '', 'days': days}
    if not db or not engine:
        return result
    try:
        from sqlalchemy import text as _text, inspect as _inspect
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)
        result['cutoff_date'] = cutoff.isoformat()
        inspector = _inspect(engine)
        table_names = set(inspector.get_table_names())
        # Archive picks
        if 'picks' in table_names:
            r = db.execute(
                _text("DELETE FROM picks WHERE created_at < :cutoff"),
                {'cutoff': cutoff},
            )
            result['deleted_picks'] = r.rowcount
            db.commit()
        # Archive completed live_sessions
        if 'live_sessions' in table_names:
            r = db.execute(
                _text(
                    "DELETE FROM live_sessions "
                    "WHERE created_at < :cutoff "
                    "AND (status = 'completed' OR status = 'ended')"
                ),
                {'cutoff': cutoff},
            )
            result['deleted_sessions'] = r.rowcount
            db.commit()
        logger.info(
            f"archive_old_picks: removed {result['deleted_picks']} picks, "
            f"{result['deleted_sessions']} sessions (older than {days} days)"
        )
    except Exception as e:
        logger.error(f"archive_old_picks error: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# Fine-grained Permission helpers  (Tier 2, item 5)
# ---------------------------------------------------------------------------

def get_user_permissions(db, username: str) -> dict:
    """Return effective permissions for *username*.

    Merges role-based permissions with per-user overrides.

    Returns a dict:
      ``effective``  – sorted list of permission strings the user currently has
      ``from_roles`` – permissions derived from the user's roles
      ``granted``    – explicit per-user grants (override adds)
      ``denied``     – explicit per-user denials (override removes)
      ``is_admin``   – True when the user has the wildcard ``'*'`` permission
    """
    result = {
        'effective': [],
        'from_roles': [],
        'granted': [],
        'denied': [],
        'is_admin': False,
    }
    if not db:
        return result
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return result

        # Accumulate role-based perms
        role_perms: set = set()
        for role in (user.roles or []):
            for perm in PERMISSIONS.get(role.name, []):
                role_perms.add(perm)

        if '*' in role_perms:
            result['is_admin'] = True
            result['from_roles'] = ALL_PERMISSIONS[:]
            result['effective'] = ALL_PERMISSIONS[:]
            return result

        result['from_roles'] = sorted(role_perms)

        # Apply per-user overrides
        overrides = (
            db.query(UserPermission)
            .filter(UserPermission.username == username)
            .all()
        )
        granted_extra: set = set()
        denied: set = set()
        for o in overrides:
            if o.granted:
                granted_extra.add(o.permission)
            else:
                denied.add(o.permission)

        result['granted'] = sorted(granted_extra)
        result['denied'] = sorted(denied)

        effective = (role_perms | granted_extra) - denied
        result['effective'] = sorted(effective)
    except Exception as e:
        logger.error(f"get_user_permissions error: {e}")
    return result


def has_permission(db, username: str, permission: str) -> bool:
    """Return True if *username* has *permission*.

    Admins (wildcard ``'*'``) automatically pass every permission check.
    """
    if not db:
        return False
    try:
        perms = get_user_permissions(db, username)
        if perms.get('is_admin'):
            return True
        return permission in perms.get('effective', [])
    except Exception as e:
        logger.error(f"has_permission error: {e}")
        return False


def set_user_permission_override(db, username: str, permission: str,
                                  granted: bool, granted_by: str = '') -> bool:
    """Grant or deny a single *permission* for *username*.

    Creates or updates the ``UserPermission`` row.
    Returns ``True`` on success.
    """
    if not db:
        return False
    try:
        existing = (
            db.query(UserPermission)
            .filter(
                UserPermission.username == username,
                UserPermission.permission == permission,
            )
            .first()
        )
        if existing:
            existing.granted = granted
            existing.granted_by = granted_by
            existing.granted_at = datetime.utcnow()
        else:
            row = UserPermission(
                username=username,
                permission=permission,
                granted=granted,
                granted_by=granted_by,
            )
            db.add(row)
        db.commit()
        return True
    except Exception as e:
        logger.error(f"set_user_permission_override error: {e}")
        db.rollback()
        return False


def remove_user_permission_override(db, username: str, permission: str) -> bool:
    """Remove a per-user override for *permission*, reverting to role-based default."""
    if not db:
        return False
    try:
        row = (
            db.query(UserPermission)
            .filter(
                UserPermission.username == username,
                UserPermission.permission == permission,
            )
            .first()
        )
        if row:
            db.delete(row)
            db.commit()
        return True
    except Exception as e:
        logger.error(f"remove_user_permission_override error: {e}")
        db.rollback()
        return False


# ---------------------------------------------------------------------------
# Notification preference helpers  (Tier 2, item 6)
# ---------------------------------------------------------------------------

_NOTIF_PREF_BOOL_FIELDS = (
    'email_enabled', 'push_enabled', 'friend_requests',
    'challenge_updates', 'trade_offers', 'team_events', 'system_announcements',
)
_NOTIF_PREF_DIGEST_VALUES = ('never', 'daily', 'weekly')


def _notif_pref_to_dict(pref) -> dict:
    return {
        'email_enabled': pref.email_enabled,
        'push_enabled': pref.push_enabled,
        'friend_requests': pref.friend_requests,
        'challenge_updates': pref.challenge_updates,
        'trade_offers': pref.trade_offers,
        'team_events': pref.team_events,
        'system_announcements': pref.system_announcements,
        'digest_frequency': pref.digest_frequency,
        'updated_at': pref.updated_at.isoformat() if pref.updated_at else None,
    }


def get_notification_prefs(db, username: str) -> dict:
    """Return notification preferences for *username*.

    Creates a default row if none exists yet.  Returns a dict of all fields or
    an empty dict on failure.
    """
    if not db:
        return {}
    try:
        pref = (
            db.query(UserNotificationPreference)
            .filter(UserNotificationPreference.username == username)
            .first()
        )
        if not pref:
            pref = UserNotificationPreference(username=username)
            db.add(pref)
            db.commit()
            db.refresh(pref)
        return _notif_pref_to_dict(pref)
    except Exception as e:
        logger.error(f"get_notification_prefs error: {e}")
        return {}


def set_notification_prefs(db, username: str, updates: dict) -> dict:
    """Update notification preferences for *username*.

    Only recognized fields are applied; unknown keys are ignored.
    Returns the updated preference dict on success, or an empty dict on failure.
    """
    if not db:
        return {}
    try:
        pref = (
            db.query(UserNotificationPreference)
            .filter(UserNotificationPreference.username == username)
            .first()
        )
        if not pref:
            pref = UserNotificationPreference(username=username)
            db.add(pref)
        for field in _NOTIF_PREF_BOOL_FIELDS:
            if field in updates:
                setattr(pref, field, bool(updates[field]))
        if 'digest_frequency' in updates:
            val = str(updates['digest_frequency']).lower()
            if val in _NOTIF_PREF_DIGEST_VALUES:
                pref.digest_frequency = val
        pref.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(pref)
        return _notif_pref_to_dict(pref)
    except Exception as e:
        logger.error(f"set_notification_prefs error: {e}")
        db.rollback()
        return {}


# ---------------------------------------------------------------------------
# A/B Testing helpers  (Item 13)
# ---------------------------------------------------------------------------

import hashlib as _hashlib


def create_experiment(db, name: str, variants: list, description: str = '',
                      created_by: str = '') -> dict:
    """Create a new recommendation experiment in *draft* status.

    Returns the serialised experiment dict on success, empty dict on failure.
    """
    if not db:
        return {}
    try:
        exp = RecommendationExperiment(
            name=name,
            description=description,
            variants=','.join(v.strip() for v in variants),
            status='draft',
            created_by=created_by,
        )
        db.add(exp)
        db.commit()
        db.refresh(exp)
        return _experiment_to_dict(exp)
    except Exception as e:
        logger.error('create_experiment error: %s', e)
        db.rollback()
        return {}


def list_experiments(db) -> list:
    """Return all experiments as a list of dicts."""
    if not db:
        return []
    try:
        exps = db.query(RecommendationExperiment).order_by(
            RecommendationExperiment.created_at.desc()
        ).all()
        return [_experiment_to_dict(e) for e in exps]
    except Exception as e:
        logger.error('list_experiments error: %s', e)
        return []


def update_experiment_status(db, experiment_id: int, status: str) -> dict:
    """Change the status of an experiment.

    Allowed transitions:  draft→active, active→paused, paused→active,
    active→concluded, paused→concluded.
    Returns the updated dict or empty dict on failure.
    """
    if not db:
        return {}
    valid = ('draft', 'active', 'paused', 'concluded')
    if status not in valid:
        return {}
    try:
        exp = db.query(RecommendationExperiment).get(experiment_id)
        if not exp:
            return {}
        exp.status = status
        if status == 'active' and not exp.started_at:
            exp.started_at = datetime.utcnow()
        if status == 'concluded':
            exp.ended_at = datetime.utcnow()
        db.commit()
        db.refresh(exp)
        return _experiment_to_dict(exp)
    except Exception as e:
        logger.error('update_experiment_status error: %s', e)
        db.rollback()
        return {}


def get_or_assign_variant(db, username: str, experiment_name: str) -> str | None:
    """Return (or assign) the variant for *username* in *experiment_name*.

    Assignment is deterministic via ``hash(username + experiment_name)`` so the
    same user always lands in the same bucket even if the row is missing.
    Returns the variant string, or ``None`` if the experiment doesn't exist /
    isn't active.
    """
    if not db or not username or not experiment_name:
        return None
    try:
        exp = (
            db.query(RecommendationExperiment)
            .filter(
                RecommendationExperiment.name == experiment_name,
                RecommendationExperiment.status == 'active',
            )
            .first()
        )
        if not exp:
            return None
        variants_list = [v.strip() for v in exp.variants.split(',') if v.strip()]
        if not variants_list:
            return None
        # Check for existing assignment
        assignment = (
            db.query(ExperimentAssignment)
            .filter(
                ExperimentAssignment.experiment_id == exp.id,
                ExperimentAssignment.username == username,
            )
            .first()
        )
        if assignment:
            return assignment.variant
        # Deterministic bucket assignment
        digest = int(_hashlib.sha256(f'{username}:{experiment_name}'.encode()).hexdigest(), 16)
        variant = variants_list[digest % len(variants_list)]
        row = ExperimentAssignment(
            experiment_id=exp.id,
            username=username,
            variant=variant,
        )
        db.add(row)
        db.commit()
        return variant
    except Exception as e:
        logger.error('get_or_assign_variant error: %s', e)
        db.rollback()
        return None


def get_experiment_variant_counts(db, experiment_id: int) -> dict:
    """Return per-variant assignment counts for *experiment_id*."""
    if not db:
        return {}
    try:
        counts: dict = {}
        assignments = (
            db.query(ExperimentAssignment)
            .filter(ExperimentAssignment.experiment_id == experiment_id)
            .all()
        )
        for a in assignments:
            counts[a.variant] = counts.get(a.variant, 0) + 1
        return counts
    except Exception as e:
        logger.error('get_experiment_variant_counts error: %s', e)
        return {}


def _experiment_to_dict(exp) -> dict:
    return {
        'id': exp.id,
        'name': exp.name,
        'description': exp.description or '',
        'variants': [v.strip() for v in exp.variants.split(',') if v.strip()],
        'status': exp.status,
        'created_by': exp.created_by or '',
        'created_at': exp.created_at.isoformat() if exp.created_at else None,
        'started_at': exp.started_at.isoformat() if exp.started_at else None,
        'ended_at': exp.ended_at.isoformat() if exp.ended_at else None,
    }


# ---------------------------------------------------------------------------
# Similar Games helper  (Item 8)
# ---------------------------------------------------------------------------

def get_similar_games(db, app_id: str, platform: str = 'steam', limit: int = 10) -> list:
    """Return up to *limit* games similar to the game identified by *app_id*.

    Similarity is computed by comparing genre/tag tokens extracted from the
    ``GameDetailsCache.details_json`` blob.  Falls back to games from the same
    platform when no cached details are available.

    Returns a list of dicts:
      ``app_id``, ``game_name``, ``platform``, ``similarity_score``
    """
    if not db:
        return []
    try:
        target = (
            db.query(GameDetailsCache)
            .filter(GameDetailsCache.app_id == str(app_id),
                    GameDetailsCache.platform == platform)
            .first()
        )
        target_tokens: set = set()
        target_name: str = ''
        if target and target.details_json:
            try:
                details = json.loads(target.details_json)
                target_name = details.get('name', '')
                # Collect genre/category tokens
                for genre in details.get('genres', []):
                    if isinstance(genre, dict):
                        target_tokens.add(genre.get('description', '').lower())
                    elif isinstance(genre, str):
                        target_tokens.add(genre.lower())
                for cat in details.get('categories', []):
                    if isinstance(cat, dict):
                        target_tokens.add(cat.get('description', '').lower())
                for tag in details.get('tags', []):
                    target_tokens.add(str(tag).lower())
            except (json.JSONDecodeError, TypeError):
                pass

        # Query all OTHER cached games on same platform
        candidates = (
            db.query(GameDetailsCache)
            .filter(GameDetailsCache.app_id != str(app_id),
                    GameDetailsCache.platform == platform)
            .limit(500)
            .all()
        )

        scored: list = []
        for cand in candidates:
            cand_tokens: set = set()
            cand_name: str = cand.app_id
            if cand.details_json:
                try:
                    det = json.loads(cand.details_json)
                    cand_name = det.get('name', cand.app_id)
                    for genre in det.get('genres', []):
                        if isinstance(genre, dict):
                            cand_tokens.add(genre.get('description', '').lower())
                        elif isinstance(genre, str):
                            cand_tokens.add(genre.lower())
                    for cat in det.get('categories', []):
                        if isinstance(cat, dict):
                            cand_tokens.add(cat.get('description', '').lower())
                    for tag in det.get('tags', []):
                        cand_tokens.add(str(tag).lower())
                except (json.JSONDecodeError, TypeError):
                    pass
            if target_tokens and cand_tokens:
                intersection = len(target_tokens & cand_tokens)
                union = len(target_tokens | cand_tokens)
                score = round(intersection / union, 4) if union else 0.0
            else:
                score = 0.0
            if score > 0:
                scored.append({
                    'app_id': cand.app_id,
                    'game_name': cand_name,
                    'platform': cand.platform,
                    'similarity_score': score,
                })
        scored.sort(key=lambda x: x['similarity_score'], reverse=True)
        return scored[:limit]
    except Exception as e:
        logger.error('get_similar_games error: %s', e)
        return []


# ---------------------------------------------------------------------------
# User Suspension helpers  (Item 5)
# ---------------------------------------------------------------------------

def suspend_user(db, username: str, reason: str, suspended_by: str,
                 duration_minutes: int | None = None) -> dict:
    """Suspend *username* for *duration_minutes* (or permanently if None).

    Returns a summary dict on success, empty dict on failure.
    """
    if not db or not username:
        return {}
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return {}
        now = datetime.utcnow()
        until = (now + timedelta(minutes=duration_minutes)) if duration_minutes else None
        user.is_suspended = True
        user.suspended_until = until
        user.suspended_reason = reason
        user.suspended_by = suspended_by
        user.suspended_at = now
        db.commit()
        return {
            'username': username,
            'is_suspended': True,
            'suspended_until': until.isoformat() if until else None,
            'suspended_reason': reason,
            'suspended_by': suspended_by,
            'suspended_at': now.isoformat(),
        }
    except Exception as e:
        logger.error('suspend_user error: %s', e)
        db.rollback()
        return {}


def unsuspend_user(db, username: str) -> bool:
    """Lift the suspension for *username*.  Returns True on success."""
    if not db or not username:
        return False
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False
        user.is_suspended = False
        user.suspended_until = None
        user.suspended_reason = None
        user.suspended_by = None
        user.suspended_at = None
        db.commit()
        return True
    except Exception as e:
        logger.error('unsuspend_user error: %s', e)
        db.rollback()
        return False


def get_user_status(db, username: str) -> dict:
    """Return account status for *username* (active / suspended / banned).

    Automatically expires time-limited suspensions that have passed.
    Returns empty dict if user not found.
    """
    if not db or not username:
        return {}
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return {}
        # Auto-expire elapsed suspensions
        if user.is_suspended and user.suspended_until:
            if user.suspended_until <= datetime.utcnow():
                user.is_suspended = False
                user.suspended_until = None
                db.commit()
        status = 'active'
        if user.is_suspended:
            status = 'suspended' if user.suspended_until else 'banned'
        return {
            'username': username,
            'status': status,
            'is_suspended': user.is_suspended,
            'suspended_until': user.suspended_until.isoformat() if user.suspended_until else None,
            'suspended_reason': user.suspended_reason,
            'suspended_by': user.suspended_by,
            'suspended_at': user.suspended_at.isoformat() if user.suspended_at else None,
        }
    except Exception as e:
        logger.error('get_user_status error: %s', e)
        return {}


def search_users_admin(db, query: str = '', role: str = '',
                       status: str = '', limit: int = 50, offset: int = 0) -> list:
    """Search users with optional filters — for admin use only.

    ``status``  – ``'active'``, ``'suspended'``, or ``'banned'`` (empty = all)
    ``role``    – role name to filter by (empty = all)
    ``query``   – partial match on username

    Returns list of dicts with ``username``, ``display_name``, ``status``,
    ``roles``, ``created_at``, ``last_seen``.
    """
    if not db:
        return []
    try:
        q = db.query(User)
        if query:
            q = q.filter(User.username.ilike(f'%{query}%'))
        if status == 'suspended':
            q = q.filter(User.is_suspended.is_(True), User.suspended_until.isnot(None))
        elif status == 'banned':
            q = q.filter(User.is_suspended.is_(True), User.suspended_until.is_(None))
        elif status == 'active':
            q = q.filter(User.is_suspended.is_(False))
        users = q.order_by(User.username).offset(offset).limit(limit).all()
        now = datetime.utcnow()
        result = []
        for u in users:
            # Auto-expire
            if u.is_suspended and u.suspended_until and u.suspended_until <= now:
                u.is_suspended = False
                u.suspended_until = None
            roles_list = [r.name for r in u.roles] if u.roles else []
            if role and role not in roles_list:
                continue
            acct_status = 'active'
            if u.is_suspended:
                acct_status = 'suspended' if u.suspended_until else 'banned'
            result.append({
                'username': u.username,
                'display_name': u.display_name or u.username,
                'status': acct_status,
                'roles': roles_list,
                'created_at': u.created_at.isoformat() if u.created_at else None,
                'last_seen': u.last_seen.isoformat() if u.last_seen else None,
            })
        db.commit()
        return result
    except Exception as e:
        logger.error('search_users_admin error: %s', e)
        return []


# ---------------------------------------------------------------------------
# User Reputation helpers  (Item 7)
# ---------------------------------------------------------------------------

def get_reputation(db, username: str) -> dict:
    """Return the reputation dict for *username*, creating a default row if needed."""
    if not db or not username:
        return {}
    try:
        rep = db.query(UserReputation).filter(UserReputation.username == username).first()
        if not rep:
            rep = UserReputation(username=username, score=REPUTATION_DEFAULT_SCORE,
                                 violation_count=0)
            db.add(rep)
            db.commit()
            db.refresh(rep)
        return {
            'username': rep.username,
            'score': rep.score,
            'violation_count': rep.violation_count,
            'last_updated': rep.last_updated.isoformat() if rep.last_updated else None,
            'last_action': rep.last_action,
        }
    except Exception as e:
        logger.error('get_reputation error: %s', e)
        return {}


def update_reputation(db, username: str, action: str) -> dict:
    """Deduct reputation for *username* based on moderation *action*.

    If the score drops below ``REPUTATION_AUTO_BAN_THRESHOLD`` the user is
    automatically suspended.  Returns updated reputation dict.
    """
    if not db or not username:
        return {}
    try:
        rep = db.query(UserReputation).filter(UserReputation.username == username).first()
        if not rep:
            # Explicitly set Python-side defaults — SQLAlchemy column defaults
            # are applied at INSERT time only and won't be available before flush.
            rep = UserReputation(username=username, score=REPUTATION_DEFAULT_SCORE,
                                violation_count=0)
            db.add(rep)
        penalty = REPUTATION_PENALTIES.get(action, REPUTATION_PENALTIES['default'])
        current_score = rep.score if rep.score is not None else REPUTATION_DEFAULT_SCORE
        rep.score = max(0, current_score - penalty)
        rep.violation_count = (rep.violation_count or 0) + 1
        rep.last_action = action
        db.commit()
        # Auto-ban if score drops below threshold
        if rep.score <= REPUTATION_AUTO_BAN_THRESHOLD:
            suspend_user(
                db, username,
                reason=f'Automatic suspension: reputation score {rep.score} below threshold',
                suspended_by='system',
                duration_minutes=None,  # permanent until reviewed
            )
        db.refresh(rep)
        return {
            'username': rep.username,
            'score': rep.score,
            'violation_count': rep.violation_count,
            'last_updated': rep.last_updated.isoformat() if rep.last_updated else None,
            'last_action': rep.last_action,
            'auto_suspended': rep.score <= REPUTATION_AUTO_BAN_THRESHOLD,
        }
    except Exception as e:
        logger.error('update_reputation error: %s', e)
        db.rollback()
        return {}


def get_low_reputation_users(db, threshold: int | None = None,
                             limit: int = 50) -> list:
    """Return users whose reputation score is at or below *threshold*.

    Defaults to ``REPUTATION_AUTO_BAN_THRESHOLD`` when not provided.
    """
    if not db:
        return []
    threshold = threshold if threshold is not None else REPUTATION_AUTO_BAN_THRESHOLD
    try:
        rows = (
            db.query(UserReputation)
            .filter(UserReputation.score <= threshold)
            .order_by(UserReputation.score)
            .limit(limit)
            .all()
        )
        return [
            {
                'username': r.username,
                'score': r.score,
                'violation_count': r.violation_count,
                'last_action': r.last_action,
                'last_updated': r.last_updated.isoformat() if r.last_updated else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error('get_low_reputation_users error: %s', e)
        return []


# ---------------------------------------------------------------------------
# User Group helpers  (Item 5)
# ---------------------------------------------------------------------------

def create_user_group(db, name: str, description: str = '',
                      created_by: str = '') -> dict:
    """Create a named user group.  Returns the group dict on success, empty on failure."""
    if not db or not name:
        return {}
    try:
        grp = UserGroup(name=name, description=description, created_by=created_by)
        db.add(grp)
        db.commit()
        db.refresh(grp)
        return _group_to_dict(grp, member_count=0)
    except Exception as e:
        logger.error('create_user_group error: %s', e)
        db.rollback()
        return {}


def list_user_groups(db) -> list:
    """Return all user groups with their member counts."""
    if not db:
        return []
    try:
        groups = db.query(UserGroup).order_by(UserGroup.name).all()
        result = []
        for grp in groups:
            count = db.query(UserGroupMember).filter(
                UserGroupMember.group_id == grp.id
            ).count()
            result.append(_group_to_dict(grp, member_count=count))
        return result
    except Exception as e:
        logger.error('list_user_groups error: %s', e)
        return []


def delete_user_group(db, group_id: int) -> bool:
    """Delete a user group and all its memberships."""
    if not db:
        return False
    try:
        db.query(UserGroupMember).filter(UserGroupMember.group_id == group_id).delete()
        deleted = db.query(UserGroup).filter(UserGroup.id == group_id).delete()
        db.commit()
        return deleted > 0
    except Exception as e:
        logger.error('delete_user_group error: %s', e)
        db.rollback()
        return False


def add_group_member(db, group_id: int, username: str, added_by: str = '') -> dict:
    """Add *username* to user group *group_id*.

    Returns ``{'ok': True, 'username': ..., 'group_id': ...}`` or error dict.
    """
    if not db:
        return {'ok': False, 'error': 'no db'}
    try:
        grp = db.get(UserGroup, group_id)
        if not grp:
            return {'ok': False, 'error': 'Group not found'}
        existing = db.query(UserGroupMember).filter(
            UserGroupMember.group_id == group_id,
            UserGroupMember.username == username,
        ).first()
        if existing:
            return {'ok': False, 'error': 'Already a member'}
        mem = UserGroupMember(group_id=group_id, username=username, added_by=added_by)
        db.add(mem)
        db.commit()
        return {'ok': True, 'username': username, 'group_id': group_id}
    except Exception as e:
        logger.error('add_group_member error: %s', e)
        db.rollback()
        return {'ok': False, 'error': str(e)}


def remove_group_member(db, group_id: int, username: str) -> bool:
    """Remove *username* from user group *group_id*."""
    if not db:
        return False
    try:
        deleted = db.query(UserGroupMember).filter(
            UserGroupMember.group_id == group_id,
            UserGroupMember.username == username,
        ).delete()
        db.commit()
        return deleted > 0
    except Exception as e:
        logger.error('remove_group_member error: %s', e)
        db.rollback()
        return False


def get_group_members(db, group_id: int) -> list:
    """Return list of member usernames for *group_id*."""
    if not db:
        return []
    try:
        members = db.query(UserGroupMember).filter(
            UserGroupMember.group_id == group_id
        ).all()
        return [m.username for m in members]
    except Exception as e:
        logger.error('get_group_members error: %s', e)
        return []


def _group_to_dict(grp, member_count: int = 0) -> dict:
    return {
        'id': grp.id,
        'name': grp.name,
        'description': grp.description or '',
        'created_by': grp.created_by or '',
        'created_at': grp.created_at.isoformat() if grp.created_at else None,
        'member_count': member_count,
    }


# ---------------------------------------------------------------------------
# Search History helpers  (Item 3 — Advanced Search)
# ---------------------------------------------------------------------------

# Maximum number of history entries kept per user.
SEARCH_HISTORY_MAX: int = 50


def record_search(db, username: str, query: str, filters: dict = None,
                  result_count: int = None) -> bool:
    """Persist a search to the user's history.

    Silently returns ``False`` on any error so callers never need to handle
    search-history failures.  Prunes older rows once the per-user cap is
    exceeded.
    """
    if not db or not username or not query:
        return False
    try:
        entry = SearchHistory(
            username=username,
            query=query[:500],
            filters=json.dumps(filters) if filters else None,
            result_count=result_count,
        )
        db.add(entry)
        db.commit()
        # Prune: keep only the most recent SEARCH_HISTORY_MAX rows per user
        all_ids = (
            db.query(SearchHistory.id)
            .filter(SearchHistory.username == username)
            .order_by(SearchHistory.searched_at.desc())
            .all()
        )
        if len(all_ids) > SEARCH_HISTORY_MAX:
            old_ids = [r.id for r in all_ids[SEARCH_HISTORY_MAX:]]
            db.query(SearchHistory).filter(SearchHistory.id.in_(old_ids)).delete(
                synchronize_session=False
            )
            db.commit()
        return True
    except Exception as e:
        logger.error('record_search error: %s', e)
        db.rollback()
        return False


def get_search_history(db, username: str, limit: int = 20) -> list:
    """Return the most recent searches for *username* (newest first)."""
    if not db or not username:
        return []
    try:
        rows = (
            db.query(SearchHistory)
            .filter(SearchHistory.username == username)
            .order_by(SearchHistory.searched_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                'id': r.id,
                'query': r.query,
                'filters': json.loads(r.filters) if r.filters else None,
                'result_count': r.result_count,
                'searched_at': r.searched_at.isoformat() if r.searched_at else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error('get_search_history error: %s', e)
        return []


def clear_search_history(db, username: str) -> bool:
    """Delete all search history for *username*."""
    if not db or not username:
        return False
    try:
        db.query(SearchHistory).filter(SearchHistory.username == username).delete()
        db.commit()
        return True
    except Exception as e:
        logger.error('clear_search_history error: %s', e)
        db.rollback()
        return False
