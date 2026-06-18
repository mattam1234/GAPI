"""Request schemas for the direct-messaging domain.

Responses (conversation and message lists) are returned as plain dicts so the
DB-layer shapes pass through verbatim.
"""
from typing import Optional

from pydantic import BaseModel


class SendMessageIn(BaseModel):
    message: Optional[str] = ""
