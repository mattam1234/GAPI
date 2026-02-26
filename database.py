#!/usr/bin/env python3
"""
Database models and configuration for GAPI.
Handles PostgreSQL connections for user data, ignored games, and achievements.
"""

import os
import json
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Table, Float, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
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

try:
    engine = create_engine(DATABASE_URL, echo=False)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()
except Exception as e:
    logger.warning(f"PostgreSQL not available, will use mock database: {e}")
    engine = None
    SessionLocal = None
    Base = object


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
    epic_id = Column(String(255), nullable=True)
    gog_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
            return True
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            return False
    return False


def get_user_by_username(db, username: str):
    """Get user from database."""
    if not db:
        return None
    try:
        return db.query(User).filter(User.username == username).first()
    except Exception as e:
        logger.error(f"Error getting user: {e}")
        return None


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
            cache_entry = GameLibraryCache(
                user_id=user.id,
                app_id=str(game.get('app_id', game.get('appid', ''))),
                game_name=game.get('name', 'Unknown'),
                platform=game.get('platform', 'steam'),
                playtime_hours=float(game.get('playtime_hours', game.get('playtime_forever', 0)) / 60 
                                   if 'playtime_forever' in game else game.get('playtime_hours', 0)),
                last_played=game.get('last_played')
            )
            db.add(cache_entry)
            count += 1
        
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
