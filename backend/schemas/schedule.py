"""Request schemas for the schedule domain.

Schedule-collection and event payloads carry service-computed fields and are
returned as plain dicts (no response_model) to pass through verbatim.
"""
from typing import Any, Optional

from pydantic import BaseModel


class CreateScheduleIn(BaseModel):
    name: Optional[str] = ""
    members: Any = None  # list or comma-separated string
    is_shared: Optional[bool] = True


class UpdateScheduleIn(BaseModel):
    name: Optional[str] = ""
    members: Any = None
    is_shared: Optional[bool] = None  # None => leave sharing unchanged
