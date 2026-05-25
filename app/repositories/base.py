"""Repository base class used by all concrete repositories."""
import json
import logging
import os
import tempfile
import threading
from typing import Any


class BaseRepository:
    """Provides JSON-backed persistence for a single data file.

    Sub-classes call :meth:`_load` to read initial data from disk and
    :meth:`_save` to atomically persist data back.  All repositories keep an
    in-memory copy in ``self.data``; callers mutate that copy and then call
    :meth:`save` to persist the change.

    The atomic write uses a write-then-rename strategy so the file is never
    left in a partially-written state.
    """

    _db_schema_ready = False
    _db_schema_lock = threading.Lock()

    def __init__(self, file_path: str, backend: str = 'file') -> None:
        self._path = file_path
        self._backend = backend
        self._log = logging.getLogger(f'gapi.repository.{type(self).__name__}')

    def _load_from_file(self, default: Any) -> Any:
        if os.path.exists(self._path):
            try:
                with open(self._path, 'r') as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, IOError) as exc:
                self._log.warning("Could not load %s: %s", self._path, exc)
        return default

    def _save_to_file(self, data: Any) -> None:
        dir_name = os.path.dirname(os.path.abspath(self._path))
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _db_available() -> bool:
        try:
            import database  # pylint: disable=import-outside-toplevel
            return bool(getattr(database, 'SessionLocal', None)) and bool(getattr(database, 'engine', None))
        except Exception:
            return False

    def _ensure_db_schema(self) -> bool:
        if BaseRepository._db_schema_ready:
            return True
        if not self._db_available():
            return False
        try:
            import database  # pylint: disable=import-outside-toplevel
            with BaseRepository._db_schema_lock:
                if not BaseRepository._db_schema_ready:
                    database.Base.metadata.create_all(
                        bind=database.engine,
                        tables=[database.RepositoryBlob.__table__],
                    )
                    BaseRepository._db_schema_ready = True
            return True
        except Exception as exc:
            self._log.warning("Could not initialize repository_blobs table: %s", exc)
            return False

    def _storage_key(self) -> str:
        return os.path.abspath(self._path)

    def _load_from_db(self, default: Any) -> Any:
        if not self._ensure_db_schema():
            return default
        try:
            import database  # pylint: disable=import-outside-toplevel
            db = database.SessionLocal()
            try:
                row = (
                    db.query(database.RepositoryBlob)
                    .filter(database.RepositoryBlob.storage_key == self._storage_key())
                    .first()
                )
                if row and row.payload:
                    try:
                        return json.loads(row.payload)
                    except (TypeError, json.JSONDecodeError) as exc:
                        self._log.warning("Invalid repository blob for %s: %s", self._path, exc)
                        return default
            finally:
                db.close()
        except Exception as exc:
            self._log.warning("Could not load repository blob for %s: %s", self._path, exc)

        # One-time migration path: load existing file and move it into DB blob storage.
        migrated = self._load_from_file(default)
        if os.path.exists(self._path):
            try:
                self._save_to_db(migrated)
                os.unlink(self._path)
            except OSError:
                pass
            except Exception as exc:
                self._log.warning("Could not migrate %s into database: %s", self._path, exc)
        return migrated

    def _save_to_db(self, data: Any) -> None:
        if not self._ensure_db_schema():
            raise RuntimeError("Database repository backend is unavailable")
        import database  # pylint: disable=import-outside-toplevel
        payload = json.dumps(data, indent=2)
        db = database.SessionLocal()
        try:
            row = (
                db.query(database.RepositoryBlob)
                .filter(database.RepositoryBlob.storage_key == self._storage_key())
                .first()
            )
            if row is None:
                row = database.RepositoryBlob(
                    storage_key=self._storage_key(),
                    payload=payload,
                )
                db.add(row)
            else:
                row.payload = payload
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        if os.path.exists(self._path):
            try:
                os.unlink(self._path)
            except OSError:
                pass

    def _load(self, default: Any) -> Any:
        """Load JSON from *self._path*, returning *default* on missing/corrupt file."""
        if self._backend == 'db':
            return self._load_from_db(default)
        return self._load_from_file(default)

    def _save(self, data: Any) -> None:
        """Atomically write *data* as JSON to *self._path*."""
        if self._backend == 'db':
            self._save_to_db(data)
            return
        self._save_to_file(data)
