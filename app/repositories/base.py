"""Repository base class used by all concrete repositories."""
import json
import logging
import os
import tempfile
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

    def __init__(self, file_path: str) -> None:
        self._path = file_path
        self._log = logging.getLogger(f'gapi.repository.{type(self).__name__}')

    def _load(self, default: Any) -> Any:
        """Load JSON from *self._path*, returning *default* on missing/corrupt file."""
        if os.path.exists(self._path):
            try:
                with open(self._path, 'r') as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, IOError) as exc:
                self._log.warning("Could not load %s: %s", self._path, exc)
        return default

    def _save(self, data: Any) -> None:
        """Atomically write *data* as JSON to *self._path*."""
        dir_name = os.path.dirname(os.path.abspath(self._path))
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
