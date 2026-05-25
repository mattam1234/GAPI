"""Business logic for backlog collections and per-game statuses."""
import datetime
import uuid
from typing import Dict, List, Optional, Tuple

from ..repositories.backlog_repository import BacklogRepository

VALID_STATUSES = ('want_to_play', 'playing', 'completed', 'dropped')
_COLLECTIONS_KEY = '__collections__'
_ENTRIES_KEY = '__entries__'
_LEGACY_COLLECTION_ID = 'legacy'


def _clean_backlog_members(members: Optional[List[str]]) -> List[str]:
    """Normalize and de-duplicate backlog member usernames."""
    clean_members: List[str] = []
    seen = set()
    for raw_member in members or []:
        member = str(raw_member or '').strip()
        if not member:
            continue
        key = member.lower()
        if key in seen:
            continue
        seen.add(key)
        clean_members.append(member)
    return clean_members


class BacklogService:
    """Creates and manages personal or shared backlog collections."""

    def __init__(self, repository: BacklogRepository) -> None:
        self._repo = repository
        self._current_user: Optional[str] = None
        self._ensure_store_shape()

    def set_current_user(self, username: Optional[str]) -> "BacklogService":
        """Bind a default user for backward-compatible calls."""
        safe_username = str(username or '').strip()
        self._current_user = safe_username or None
        return self

    def _now_iso(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def _default_collection_id(self, username: str) -> str:
        return f'personal:{str(username or "").strip().lower()}'

    def _effective_username(self, username: Optional[str] = None) -> Optional[str]:
        safe_username = str(username or '').strip()
        if safe_username:
            return safe_username
        return self._current_user

    def _ensure_store_shape(self) -> None:
        """Normalize repository payload to the v2 collections+entries envelope."""
        changed = False
        root = self._repo.data if isinstance(self._repo.data, dict) else {}
        collections = root.get(_COLLECTIONS_KEY)
        entries = root.get(_ENTRIES_KEY)

        if not isinstance(collections, dict) or not isinstance(entries, dict):
            collections = {}
            entries = {}
            legacy_entries = {
                str(key): str(value)
                for key, value in root.items()
                if not str(key).startswith('__') and isinstance(value, str)
            }
            if legacy_entries:
                now = self._now_iso()
                collections[_LEGACY_COLLECTION_ID] = {
                    'id': _LEGACY_COLLECTION_ID,
                    'name': 'My Backlog',
                    'owner': 'legacy',
                    'members': ['legacy'],
                    'is_shared': False,
                    'created_at': now,
                    'updated_at': now,
                }
                entries[_LEGACY_COLLECTION_ID] = legacy_entries
            changed = True

        self._repo.data = {
            _COLLECTIONS_KEY: collections,
            _ENTRIES_KEY: entries,
        }
        if changed:
            self._repo.save()

    def _get_collections(self) -> Dict[str, Dict]:
        return self._repo.data.setdefault(_COLLECTIONS_KEY, {})

    def _get_entries(self) -> Dict[str, Dict[str, str]]:
        return self._repo.data.setdefault(_ENTRIES_KEY, {})

    def _get_collection_entries(self, collection_id: str) -> Dict[str, str]:
        return self._get_entries().setdefault(collection_id, {})

    def get_collection_entry_count(self, collection_id: Optional[str]) -> int:
        """Return number of stored entries for ``collection_id``."""
        safe_collection_id = str(collection_id or '').strip()
        if not safe_collection_id:
            return 0
        return len(self._get_entries().get(safe_collection_id, {}))

    def _ensure_legacy_collection(self) -> str:
        collections = self._get_collections()
        if _LEGACY_COLLECTION_ID not in collections:
            now = self._now_iso()
            collections[_LEGACY_COLLECTION_ID] = {
                'id': _LEGACY_COLLECTION_ID,
                'name': 'My Backlog',
                'owner': 'legacy',
                'members': ['legacy'],
                'is_shared': False,
                'created_at': now,
                'updated_at': now,
            }
            self._get_entries().setdefault(_LEGACY_COLLECTION_ID, {})
            self._repo.save()
        return _LEGACY_COLLECTION_ID

    def _can_access_collection(self, collection: Optional[Dict], username: Optional[str]) -> bool:
        if not collection:
            return False
        safe_username = self._effective_username(username)
        if not safe_username:
            return True
        owner = str(collection.get('owner') or '').strip().lower()
        members = {str(member).strip().lower() for member in (collection.get('members') or [])}
        return safe_username.lower() == owner or safe_username.lower() in members

    def is_default_collection_id(self, collection_id: str, username: Optional[str]) -> bool:
        safe_username = self._effective_username(username)
        if not safe_username:
            return str(collection_id or '').strip() == _LEGACY_COLLECTION_ID
        return str(collection_id or '').strip().lower() == self._default_collection_id(safe_username).lower()

    def ensure_default_collection(self, username: Optional[str]) -> Optional[Dict]:
        """Ensure each user has a personal default backlog container."""
        safe_username = self._effective_username(username)
        if not safe_username:
            legacy_id = self._ensure_legacy_collection()
            return self._get_collections().get(legacy_id)
        collection_id = self._default_collection_id(safe_username)
        collections = self._get_collections()
        existing = collections.get(collection_id)
        if existing:
            return existing
        now = self._now_iso()
        collection = {
            'id': collection_id,
            'name': 'My Backlog',
            'owner': safe_username,
            'members': [safe_username],
            'is_shared': False,
            'created_at': now,
            'updated_at': now,
        }
        collections[collection_id] = collection
        self._get_entries().setdefault(collection_id, {})
        self._repo.save()
        return collection

    def list_collections(self, username: Optional[str] = None) -> List[Dict]:
        """List backlogs visible to *username*."""
        safe_username = self._effective_username(username)
        if safe_username:
            self.ensure_default_collection(safe_username)
        elif not self._get_collections():
            self.ensure_default_collection(None)
        collections = list(self._get_collections().values())
        if safe_username:
            collections = [item for item in collections if self._can_access_collection(item, safe_username)]
        collections.sort(key=lambda item: (
            0 if self.is_default_collection_id(item.get('id', ''), safe_username) else 1,
            0 if str(item.get('owner') or '').strip().lower() == str(safe_username or '').lower() else 1,
            0 if not item.get('is_shared') else 1,
            str(item.get('name') or '').lower(),
        ))
        return collections

    def resolve_collection_for_user(self, requested_collection_id: Optional[str],
                                    username: Optional[str]) -> Optional[str]:
        """Resolve a requested backlog ID to one the user is allowed to access."""
        safe_requested_id = str(requested_collection_id or '').strip()
        collections = self.list_collections(username)
        if safe_requested_id and any(item.get('id') == safe_requested_id for item in collections):
            return safe_requested_id
        default_collection = self.ensure_default_collection(username)
        if default_collection:
            return default_collection.get('id')
        return collections[0]['id'] if collections else None

    def get_collection(self, collection_id: Optional[str]) -> Optional[Dict]:
        safe_collection_id = str(collection_id or '').strip()
        if not safe_collection_id:
            return None
        return self._get_collections().get(safe_collection_id)

    def create_collection(self, name: str, owner_username: str,
                          members: Optional[List[str]] = None,
                          is_shared: bool = True) -> Dict:
        """Create a new backlog collection."""
        owner = str(owner_username or '').strip()
        title = str(name or '').strip() or 'Shared Backlog'
        if not owner:
            raise ValueError('owner_username is required')
        collection_id = str(uuid.uuid4())[:8]
        now = self._now_iso()
        clean_members = _clean_backlog_members([owner] + (members or []))
        collection = {
            'id': collection_id,
            'name': title,
            'owner': owner,
            'members': clean_members,
            'is_shared': bool(is_shared or len(clean_members) > 1),
            'created_at': now,
            'updated_at': now,
        }
        self._get_collections()[collection_id] = collection
        self._get_entries()[collection_id] = {}
        self._repo.save()
        return collection

    def update_collection(self, collection_id: str, username: str, name: str,
                          members: Optional[List[str]] = None,
                          is_shared: Optional[bool] = None) -> Optional[Dict]:
        """Rename or re-share an existing backlog owned by *username*."""
        safe_collection_id = str(collection_id or '').strip()
        safe_username = str(username or '').strip()
        safe_name = str(name or '').strip()
        if not safe_collection_id or not safe_username or not safe_name:
            return None
        collection = self._get_collections().get(safe_collection_id)
        if not collection:
            return None
        if str(collection.get('owner') or '').strip().lower() != safe_username.lower():
            return None
        clean_members = _clean_backlog_members([safe_username] + (members or []))
        collection['name'] = safe_name
        collection['members'] = clean_members
        collection['is_shared'] = bool(is_shared) if is_shared is not None else len(clean_members) > 1
        collection['updated_at'] = self._now_iso()
        self._repo.save()
        return collection

    def delete_collection(self, collection_id: str, username: Optional[str]) -> bool:
        """Delete a backlog collection owned by *username*."""
        safe_collection_id = str(collection_id or '').strip()
        safe_username = self._effective_username(username)
        if not safe_collection_id or not safe_username:
            return False
        if self.is_default_collection_id(safe_collection_id, safe_username):
            return False
        collection = self._get_collections().get(safe_collection_id)
        if not collection:
            return False
        if str(collection.get('owner') or '').strip().lower() != safe_username.lower():
            return False
        del self._get_collections()[safe_collection_id]
        self._get_entries().pop(safe_collection_id, None)
        self._repo.save()
        return True

    def leave_collection(self, collection_id: str, username: Optional[str]) -> bool:
        """Leave a shared backlog collection."""
        safe_collection_id = str(collection_id or '').strip()
        safe_username = self._effective_username(username)
        if not safe_collection_id or not safe_username:
            return False
        if self.is_default_collection_id(safe_collection_id, safe_username):
            return False
        collection = self._get_collections().get(safe_collection_id)
        if not collection:
            return False
        if str(collection.get('owner') or '').strip().lower() == safe_username.lower():
            return False
        members = _clean_backlog_members(collection.get('members') or [])
        filtered = [member for member in members if member.lower() != safe_username.lower()]
        if len(filtered) == len(members):
            return False
        collection['members'] = filtered
        collection['is_shared'] = len(filtered) > 1
        collection['updated_at'] = self._now_iso()
        self._repo.save()
        return True

    def _resolve_context(self, username: Optional[str] = None,
                         collection_id: Optional[str] = None) -> Tuple[Optional[str], Optional[Dict]]:
        safe_username = self._effective_username(username)
        safe_collection_id = str(collection_id or '').strip()
        if safe_collection_id:
            collection = self.get_collection(safe_collection_id)
            if not collection or not self._can_access_collection(collection, safe_username):
                return None, None
            return safe_collection_id, collection
        resolved_collection_id = self.resolve_collection_for_user(None, safe_username)
        if not resolved_collection_id:
            return None, None
        return resolved_collection_id, self.get_collection(resolved_collection_id)

    def set_status(self, game_id: str, status: str, username: Optional[str] = None,
                   collection_id: Optional[str] = None) -> bool:
        """Set the backlog status for *game_id* within a collection."""
        if status not in VALID_STATUSES:
            return False
        resolved_collection_id, _ = self._resolve_context(username=username, collection_id=collection_id)
        if not resolved_collection_id:
            return False
        self._get_collection_entries(resolved_collection_id)[str(game_id)] = status
        self._repo.save()
        return True

    def remove(self, game_id: str, username: Optional[str] = None,
               collection_id: Optional[str] = None) -> bool:
        """Remove *game_id* from the resolved backlog collection."""
        resolved_collection_id, _ = self._resolve_context(username=username, collection_id=collection_id)
        if not resolved_collection_id:
            return False
        entries = self._get_collection_entries(resolved_collection_id)
        safe_game_id = str(game_id)
        if safe_game_id not in entries:
            return False
        del entries[safe_game_id]
        self._repo.save()
        return True

    def get_status(self, game_id: str, username: Optional[str] = None,
                   collection_id: Optional[str] = None) -> Optional[str]:
        """Return the backlog status for *game_id* in the resolved collection."""
        resolved_collection_id, _ = self._resolve_context(username=username, collection_id=collection_id)
        if not resolved_collection_id:
            return None
        return self._get_collection_entries(resolved_collection_id).get(str(game_id))

    def get_games(self, all_games: List[Dict], status: Optional[str] = None,
                  username: Optional[str] = None,
                  collection_id: Optional[str] = None) -> List[Dict]:
        """Return game dicts for backlog entries in the resolved collection."""
        resolved_collection_id, _ = self._resolve_context(username=username, collection_id=collection_id)
        if not resolved_collection_id:
            return []
        id_to_status = dict(self._get_collection_entries(resolved_collection_id))
        if status:
            id_to_status = {key: value for key, value in id_to_status.items() if value == status}
        id_set = set(id_to_status)
        result = []
        for game in all_games:
            candidate_ids = []
            gid = str(game.get('game_id') or '').strip()
            if gid:
                candidate_ids.append(gid)
                if ':' in gid:
                    suffix = gid.rsplit(':', 1)[-1].strip()
                    if suffix:
                        candidate_ids.append(suffix)
            app_id = str(game.get('app_id') or game.get('appid') or '').strip()
            if app_id:
                candidate_ids.append(app_id)
                if ':' not in gid:
                    platform = str(game.get('platform') or 'steam').strip().lower()
                    candidate_ids.append(f'{platform}:{app_id}')
                    candidate_ids.append(f'steam:{app_id}')
            matched_id = next((candidate for candidate in candidate_ids if candidate in id_set), None)
            if matched_id:
                entry = dict(game)
                entry['backlog_status'] = id_to_status[matched_id]
                result.append(entry)
        return result
