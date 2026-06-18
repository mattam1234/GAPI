"""Response schemas for the user-profile domain."""
from pydantic import BaseModel


class MyProfile(BaseModel):
    username: str
    bio: str = ""
    status: str = ""
    favorite_game: str = ""
    is_private: bool = False


class ProfileUpdateResult(BaseModel):
    success: bool = True
    message: str = "Profile updated"
