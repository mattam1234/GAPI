"""Services package — expose all concrete services from one import."""
from .review_service import ReviewService
from .tag_service import TagService
from .schedule_service import ScheduleService
from .playlist_service import PlaylistService
from .backlog_service import BacklogService
from .budget_service import BudgetService
from .wishlist_service import WishlistService
from .favorites_service import FavoritesService
from .history_service import HistoryService
from .notification_service import NotificationService
from .chat_service import ChatService
from .friend_service import FriendService
from .leaderboard_service import LeaderboardService
from .plugin_service import PluginService
from .app_settings_service import AppSettingsService
from .ignored_games_service import IgnoredGamesService
from .library_service import LibraryService
from .db_favorites_service import DBFavoritesService
from .user_service import UserService
from .achievement_service import AchievementService
from .recommendation_service import SmartRecommendationEngine

__all__ = [
    'ReviewService',
    'TagService',
    'ScheduleService',
    'PlaylistService',
    'BacklogService',
    'BudgetService',
    'WishlistService',
    'FavoritesService',
    'HistoryService',
    'NotificationService',
    'ChatService',
    'FriendService',
    'LeaderboardService',
    'PluginService',
    'AppSettingsService',
    'IgnoredGamesService',
    'LibraryService',
    'DBFavoritesService',
    'UserService',
    'AchievementService',
    'SmartRecommendationEngine',
]
