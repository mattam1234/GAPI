"""Request schemas for the voting domain.

Responses (voting-session dicts via ``session.to_dict()`` and the close payload)
are returned as plain dicts so their shapes pass through verbatim.
"""
from typing import Any, Optional

from pydantic import BaseModel


class CreateVotingIn(BaseModel):
    users: Optional[Any] = None
    num_candidates: Any = 5
    duration: Optional[Any] = None
    coop_only: bool = False
    voting_method: str = "plurality"


class CastVoteIn(BaseModel):
    user_name: Optional[str] = ""
    app_id: Optional[Any] = None
    ranking: Optional[Any] = None
