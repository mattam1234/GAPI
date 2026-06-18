"""Request schemas for the backlog domain.

Responses are returned as plain dicts (no response_model): the backlog
collection and entry payloads carry many service-computed fields
(entry_count, invited_count, backlog_status, active_backlog, ...) that must
pass through verbatim, so they are intentionally not reshaped by Pydantic.
"""
from typing import Any, Optional

from pydantic import BaseModel


class CreateBacklogIn(BaseModel):
    name: Optional[str] = ""
    # members may be a list of usernames or a comma-separated string; the legacy
    # _parse_shared_member_usernames helper normalises both.
    members: Any = None
    is_shared: Optional[bool] = True


class UpdateBacklogIn(BaseModel):
    name: Optional[str] = ""
    members: Any = None
    is_shared: Optional[bool] = None  # None => leave sharing unchanged


class SetBacklogStatusIn(BaseModel):
    status: Optional[str] = ""
    notes: Optional[Any] = None
    collection_id: Optional[str] = None
