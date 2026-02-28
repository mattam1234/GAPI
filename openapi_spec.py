"""
openapi_spec.py  —  GAPI OpenAPI 3.0 specification builder.

Returns a Python dict (compatible with ``json.dumps``) that describes every
REST endpoint exposed by ``gapi_gui.py``.  The dict is intentionally built in
pure Python so that it can be generated at import time with zero additional
runtime dependencies.

Usage (from gapi_gui.py)::

    from openapi_spec import build_spec
    spec = build_spec(server_url="http://localhost:5000")
"""

from typing import Any, Dict


def _ref(name: str) -> Dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _resp(description: str, schema: Dict = None) -> Dict:
    content: Dict[str, Any] = {}
    if schema:
        content = {"application/json": {"schema": schema}}
    r: Dict[str, Any] = {"description": description}
    if content:
        r["content"] = content
    return r


def _json_resp(description: str, schema: Dict = None) -> Dict:
    if schema is None:
        schema = {"type": "object"}
    return _resp(description, schema)


def _success() -> Dict:
    return _json_resp("Success", {"type": "object",
                                  "properties": {"success": {"type": "boolean"}}})


def _error(code: int = 400) -> Dict:
    return _json_resp("Error", {"type": "object",
                                "properties": {"error": {"type": "string"}}})


def build_spec(server_url: str = "/") -> Dict[str, Any]:
    """Return the full OpenAPI 3.0 specification dict."""

    spec: Dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {
            "title": "GAPI — Multi-Platform Game Picker API",
            "version": "2.5.0",
            "description": (
                "REST API for GAPI, a multi-platform game picker that supports Steam, "
                "Epic Games, and GOG libraries with features such as smart recommendations, "
                "multi-user voting, game reviews, playlists, backlog management, budget "
                "tracking, and wishlist sale alerts.\n\n"
                "All endpoints that return user-specific data require an active session "
                "(log in via `POST /api/auth/login` first)."
            ),
            "contact": {"url": "https://github.com/mattam1234/GAPI"},
            "license": {"name": "MIT"},
        },
        "servers": [{"url": server_url, "description": "GAPI server"}],
        "tags": [
            {"name": "auth",          "description": "Authentication and user management"},
            {"name": "library",       "description": "Game library operations"},
            {"name": "pick",          "description": "Game picking and random selection"},
            {"name": "favorites",     "description": "Favourites list"},
            {"name": "reviews",       "description": "Personal game reviews and ratings"},
            {"name": "tags",          "description": "Custom game tags"},
            {"name": "recommendations","description": "Smart game recommendations"},
            {"name": "backlog",       "description": "Game backlog status tracking"},
            {"name": "playlists",     "description": "Custom game playlists"},
            {"name": "schedule",      "description": "Game night scheduler"},
            {"name": "multiuser",     "description": "Multi-user and co-op features"},
            {"name": "voting",        "description": "Plurality and ranked-choice voting"},
            {"name": "budget",        "description": "Purchase price / budget tracking"},
            {"name": "wishlist",      "description": "Wishlist and sale alerts"},
            {"name": "stats",         "description": "Library and playtime statistics"},
            {"name": "export",        "description": "CSV export"},
            {"name": "achievements",  "description": "Steam achievement tracking"},
            {"name": "friends",       "description": "Steam friend activity"},
            {"name": "admin",         "description": "Admin-only operations"},
            {"name": "docs",          "description": "API documentation"},
        ],
        "components": {
            "schemas": {
                "Error": {
                    "type": "object",
                    "properties": {"error": {"type": "string"}},
                    "required": ["error"],
                },
                "Success": {
                    "type": "object",
                    "properties": {"success": {"type": "boolean", "example": True}},
                },
                "Game": {
                    "type": "object",
                    "properties": {
                        "appid":              {"type": "integer", "example": 620},
                        "name":               {"type": "string",  "example": "Portal 2"},
                        "playtime_forever":   {"type": "integer", "example": 120,
                                               "description": "Total playtime in minutes"},
                        "img_icon_url":       {"type": "string"},
                        "platform":           {"type": "string",  "example": "steam"},
                    },
                },
                "Review": {
                    "type": "object",
                    "properties": {
                        "game_id":   {"type": "string"},
                        "rating":    {"type": "integer", "minimum": 1, "maximum": 10},
                        "notes":     {"type": "string"},
                        "review_date": {"type": "string", "format": "date"},
                    },
                },
                "BacklogStatus": {
                    "type": "string",
                    "enum": ["want_to_play", "playing", "completed", "dropped"],
                },
                "BudgetEntry": {
                    "type": "object",
                    "properties": {
                        "game_id":       {"type": "string"},
                        "price":         {"type": "number", "minimum": 0},
                        "currency":      {"type": "string", "example": "USD"},
                        "purchase_date": {"type": "string", "format": "date"},
                        "notes":         {"type": "string"},
                    },
                },
                "WishlistEntry": {
                    "type": "object",
                    "properties": {
                        "game_id":      {"type": "string", "example": "steam:620"},
                        "name":         {"type": "string", "example": "Portal 2"},
                        "platform":     {"type": "string", "example": "steam"},
                        "added_date":   {"type": "string", "format": "date"},
                        "target_price": {"type": "number", "nullable": True,
                                         "description": "Alert when price drops at or below this value"},
                        "notes":        {"type": "string"},
                    },
                },
                "VotingSession": {
                    "type": "object",
                    "properties": {
                        "session_id":    {"type": "string"},
                        "candidates":    {"type": "array", "items": {"type": "string"}},
                        "voting_method": {"type": "string", "enum": ["plurality", "ranked_choice"]},
                        "expires_at":    {"type": "string", "format": "date-time"},
                        "votes":         {"type": "object", "additionalProperties": {"type": "integer"}},
                    },
                },
            },
            "securitySchemes": {
                "sessionCookie": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": "session",
                    "description": "Session cookie obtained from POST /api/auth/login",
                }
            },
        },
        "security": [{"sessionCookie": []}],
        "paths": _build_paths(),
    }
    return spec


def _build_paths() -> Dict[str, Any]:  # noqa: C901 – intentionally long
    paths: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    paths["/api/auth/login"] = {
        "post": {
            "tags": ["auth"],
            "summary": "Log in",
            "description": "Authenticate with username + password. Sets a session cookie.",
            "security": [],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["username", "password"],
                    "properties": {
                        "username": {"type": "string"},
                        "password": {"type": "string", "format": "password"},
                    },
                }}},
            },
            "responses": {
                "200": _json_resp("Logged in successfully",
                                  {"type": "object",
                                   "properties": {"message": {"type": "string"},
                                                  "username": {"type": "string"},
                                                  "role": {"type": "string"}}}),
                "401": _json_resp("Invalid credentials", _ref("Error")),
            },
        }
    }
    paths["/api/auth/logout"] = {
        "post": {
            "tags": ["auth"],
            "summary": "Log out",
            "description": "Clear the current session.",
            "responses": {"200": _json_resp("Logged out", _ref("Success"))},
        }
    }
    paths["/api/auth/current"] = {
        "get": {
            "tags": ["auth"],
            "summary": "Get current user",
            "description": "Returns the currently authenticated user's info.",
            "responses": {
                "200": _json_resp("Current user info",
                                  {"type": "object",
                                   "properties": {"username": {"type": "string"},
                                                  "role": {"type": "string"}}}),
                "401": _json_resp("Not authenticated", _ref("Error")),
            },
        }
    }
    paths["/api/auth/register"] = {
        "post": {
            "tags": ["auth"],
            "summary": "Register a new user",
            "security": [],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["username", "password"],
                    "properties": {
                        "username": {"type": "string"},
                        "password": {"type": "string", "format": "password"},
                    },
                }}},
            },
            "responses": {
                "201": _json_resp("User created", _ref("Success")),
                "400": _json_resp("Validation error", _ref("Error")),
                "409": _json_resp("Username already taken", _ref("Error")),
            },
        }
    }

    # ------------------------------------------------------------------
    # Status / Setup
    # ------------------------------------------------------------------
    paths["/api/status"] = {
        "get": {
            "tags": ["admin"],
            "summary": "Server status",
            "security": [],
            "responses": {"200": _json_resp("Status object",
                                             {"type": "object",
                                              "properties": {
                                                  "status": {"type": "string"},
                                                  "version": {"type": "string"},
                                              }})},
        }
    }
    paths["/api/setup/status"] = {
        "get": {
            "tags": ["admin"],
            "summary": "Check whether initial setup has been completed",
            "security": [],
            "responses": {"200": _json_resp("Setup status", {"type": "object"})},
        }
    }
    paths["/api/setup/initial-admin"] = {
        "post": {
            "tags": ["admin"],
            "summary": "Create the first admin account (one-time setup)",
            "security": [],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["username", "password"],
                    "properties": {"username": {"type": "string"},
                                   "password": {"type": "string", "format": "password"}},
                }}},
            },
            "responses": {
                "201": _json_resp("Admin created", _ref("Success")),
                "409": _json_resp("Setup already done", _ref("Error")),
            },
        }
    }

    # ------------------------------------------------------------------
    # Library
    # ------------------------------------------------------------------
    paths["/api/library"] = {
        "get": {
            "tags": ["library"],
            "summary": "Get the merged game library for the current user",
            "parameters": [
                {"name": "platform", "in": "query", "schema": {"type": "string"},
                 "description": "Filter by platform (steam / epic / gog)"},
            ],
            "responses": {
                "200": _json_resp("List of games",
                                  {"type": "object",
                                   "properties": {"games": {"type": "array",
                                                            "items": _ref("Game")},
                                                  "total": {"type": "integer"}}}),
            },
        }
    }
    paths["/api/library/sync"] = {
        "post": {
            "tags": ["library"],
            "summary": "Re-fetch the game library from all configured platforms",
            "responses": {"200": _json_resp("Sync result", {"type": "object"})},
        }
    }
    paths["/api/library/by-tag/{tag}"] = {
        "get": {
            "tags": ["library", "tags"],
            "summary": "Get library games that have a specific tag",
            "parameters": [{"name": "tag", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "responses": {"200": _json_resp("Games with tag", {"type": "object"})},
        }
    }

    # ------------------------------------------------------------------
    # Pick
    # ------------------------------------------------------------------
    paths["/api/pick"] = {
        "post": {
            "tags": ["pick"],
            "summary": "Pick a random game from the library",
            "requestBody": {
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "count":         {"type": "integer", "minimum": 1, "maximum": 10,
                                          "default": 1, "description": "Number of games to pick"},
                        "filter":        {"type": "string",
                                          "enum": ["all", "unplayed", "barely_played", "well_played"],
                                          "default": "all"},
                        "genre":         {"type": "string", "description": "Required genre"},
                        "exclude_genre": {"type": "string"},
                        "tag":           {"type": "string"},
                        "platform":      {"type": "string"},
                        "min_score":     {"type": "integer", "minimum": 0, "maximum": 100},
                        "min_year":      {"type": "integer"},
                        "max_year":      {"type": "integer"},
                    },
                }}},
            },
            "responses": {
                "200": _json_resp("Picked game(s)",
                                  {"type": "object",
                                   "properties": {"game": _ref("Game"),
                                                  "games": {"type": "array",
                                                            "items": _ref("Game")}}}),
                "404": _json_resp("No games found matching criteria", _ref("Error")),
            },
        }
    }

    # ------------------------------------------------------------------
    # Game details
    # ------------------------------------------------------------------
    paths["/api/game/{app_id}/details"] = {
        "get": {
            "tags": ["library"],
            "summary": "Get detailed info for a Steam game (Metacritic, genres, release date, ProtonDB)",
            "parameters": [{"name": "app_id", "in": "path", "required": True,
                             "schema": {"type": "integer"}}],
            "responses": {
                "200": _json_resp("Game details", {"type": "object"}),
                "404": _json_resp("Not found", _ref("Error")),
            },
        }
    }

    # ------------------------------------------------------------------
    # Favorites
    # ------------------------------------------------------------------
    paths["/api/favorites"] = {
        "get": {
            "tags": ["favorites"],
            "summary": "List all favourite games",
            "responses": {"200": _json_resp("Favourites",
                                             {"type": "object",
                                              "properties": {"favorites": {
                                                  "type": "array",
                                                  "items": _ref("Game")}}})},
        }
    }
    paths["/api/favorite/{app_id}"] = {
        "post": {
            "tags": ["favorites"],
            "summary": "Add a game to favourites",
            "parameters": [{"name": "app_id", "in": "path", "required": True,
                             "schema": {"type": "integer"}}],
            "responses": {"200": _json_resp("Added", _ref("Success"))},
        },
        "delete": {
            "tags": ["favorites"],
            "summary": "Remove a game from favourites",
            "parameters": [{"name": "app_id", "in": "path", "required": True,
                             "schema": {"type": "integer"}}],
            "responses": {"200": _json_resp("Removed", _ref("Success"))},
        },
    }

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------
    paths["/api/reviews"] = {
        "get": {
            "tags": ["reviews"],
            "summary": "List all personal game reviews",
            "responses": {"200": _json_resp("Reviews",
                                             {"type": "object",
                                              "properties": {"reviews": {
                                                  "type": "object",
                                                  "additionalProperties": _ref("Review")}}})},
        }
    }
    paths["/api/reviews/{game_id}"] = {
        "get": {
            "tags": ["reviews"],
            "summary": "Get the review for a specific game",
            "parameters": [{"name": "game_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "responses": {
                "200": _json_resp("Review", _ref("Review")),
                "404": _json_resp("No review found", _ref("Error")),
            },
        },
        "post": {
            "tags": ["reviews"],
            "summary": "Add or update a game review",
            "parameters": [{"name": "game_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "rating": {"type": "integer", "minimum": 1, "maximum": 10},
                        "notes":  {"type": "string"},
                    },
                }}},
            },
            "responses": {"200": _json_resp("Saved", _ref("Success"))},
        },
        "delete": {
            "tags": ["reviews"],
            "summary": "Delete a game review",
            "parameters": [{"name": "game_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "responses": {
                "200": _json_resp("Deleted", _ref("Success")),
                "404": _json_resp("Not found", _ref("Error")),
            },
        },
    }

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------
    paths["/api/tags"] = {
        "get": {
            "tags": ["tags"],
            "summary": "List all tags and the games they are applied to",
            "responses": {"200": _json_resp("Tags map", {"type": "object"})},
        }
    }
    paths["/api/tags/{game_id}"] = {
        "get": {
            "tags": ["tags"],
            "summary": "Get tags for a specific game",
            "parameters": [{"name": "game_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "responses": {"200": _json_resp("Tags", {"type": "object"})},
        },
        "post": {
            "tags": ["tags"],
            "summary": "Add a tag to a game",
            "parameters": [{"name": "game_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["tag"],
                    "properties": {"tag": {"type": "string"}},
                }}},
            },
            "responses": {"200": _json_resp("Added", _ref("Success"))},
        },
    }
    paths["/api/tags/{game_id}/{tag}"] = {
        "delete": {
            "tags": ["tags"],
            "summary": "Remove a tag from a game",
            "parameters": [
                {"name": "game_id", "in": "path", "required": True, "schema": {"type": "string"}},
                {"name": "tag",     "in": "path", "required": True, "schema": {"type": "string"}},
            ],
            "responses": {
                "200": _json_resp("Removed", _ref("Success")),
                "404": _json_resp("Tag not found", _ref("Error")),
            },
        }
    }

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------
    paths["/api/recommendations"] = {
        "get": {
            "tags": ["recommendations"],
            "summary": "Get personalised game recommendations",
            "description": (
                "Scores every unplayed/barely-played game by genre affinity built from "
                "well-played games in the library.  Applies a recency penalty for recently "
                "picked games."
            ),
            "parameters": [
                {"name": "count", "in": "query", "schema": {"type": "integer", "default": 10},
                 "description": "Maximum number of recommendations to return (5, 10, or 20)"},
            ],
            "responses": {
                "200": _json_resp("Recommendations",
                                  {"type": "object",
                                   "properties": {"recommendations": {
                                       "type": "array",
                                       "items": {"allOf": [_ref("Game"),
                                                           {"type": "object",
                                                            "properties": {
                                                                "recommendation_score":  {"type": "number"},
                                                                "recommendation_reason": {"type": "string"},
                                                            }}]}
                                   }}}),
            },
        }
    }

    # ------------------------------------------------------------------
    # Backlog
    # ------------------------------------------------------------------
    paths["/api/backlog"] = {
        "get": {
            "tags": ["backlog"],
            "summary": "List all backlog entries",
            "responses": {"200": _json_resp("Backlog", {"type": "object"})},
        }
    }
    paths["/api/backlog/{game_id}"] = {
        "get": {
            "tags": ["backlog"],
            "summary": "Get the backlog status for a specific game",
            "parameters": [{"name": "game_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "responses": {
                "200": _json_resp("Status", {"type": "object",
                                              "properties": {"game_id": {"type": "string"},
                                                             "status": _ref("BacklogStatus")}}),
                "404": _json_resp("Not found", _ref("Error")),
            },
        },
        "post": {
            "tags": ["backlog"],
            "summary": "Set the backlog status for a game",
            "parameters": [{"name": "game_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": _ref("BacklogStatus")},
                }}},
            },
            "responses": {"200": _json_resp("Updated", _ref("Success"))},
        },
        "delete": {
            "tags": ["backlog"],
            "summary": "Remove a game from the backlog",
            "parameters": [{"name": "game_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "responses": {
                "200": _json_resp("Removed", _ref("Success")),
                "404": _json_resp("Not found", _ref("Error")),
            },
        },
    }

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------
    paths["/api/playlists"] = {
        "get": {
            "tags": ["playlists"],
            "summary": "List all playlists",
            "responses": {"200": _json_resp("Playlists", {"type": "object"})},
        },
        "post": {
            "tags": ["playlists"],
            "summary": "Create a new playlist",
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {"name": {"type": "string"}},
                }}},
            },
            "responses": {
                "201": _json_resp("Created", _ref("Success")),
                "409": _json_resp("Name already exists", _ref("Error")),
            },
        },
    }
    paths["/api/playlists/{name}"] = {
        "delete": {
            "tags": ["playlists"],
            "summary": "Delete a playlist",
            "parameters": [{"name": "name", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "responses": {
                "200": _json_resp("Deleted", _ref("Success")),
                "404": _json_resp("Not found", _ref("Error")),
            },
        }
    }
    paths["/api/playlists/{name}/games"] = {
        "get": {
            "tags": ["playlists"],
            "summary": "List games in a playlist",
            "parameters": [{"name": "name", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "responses": {"200": _json_resp("Games", {"type": "object"})},
        },
        "post": {
            "tags": ["playlists"],
            "summary": "Add a game to a playlist",
            "parameters": [{"name": "name", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["game_id"],
                    "properties": {"game_id": {"type": "string"}},
                }}},
            },
            "responses": {"200": _json_resp("Added", _ref("Success"))},
        },
    }
    paths["/api/playlists/{name}/games/{game_id}"] = {
        "delete": {
            "tags": ["playlists"],
            "summary": "Remove a game from a playlist",
            "parameters": [
                {"name": "name",    "in": "path", "required": True, "schema": {"type": "string"}},
                {"name": "game_id", "in": "path", "required": True, "schema": {"type": "string"}},
            ],
            "responses": {
                "200": _json_resp("Removed", _ref("Success")),
                "404": _json_resp("Not found", _ref("Error")),
            },
        }
    }

    # ------------------------------------------------------------------
    # Schedule
    # ------------------------------------------------------------------
    paths["/api/schedule"] = {
        "get": {
            "tags": ["schedule"],
            "summary": "List all scheduled game-night events",
            "responses": {"200": _json_resp("Events", {"type": "object"})},
        },
        "post": {
            "tags": ["schedule"],
            "summary": "Create a new game-night event",
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["title", "event_datetime"],
                    "properties": {
                        "title":          {"type": "string"},
                        "event_datetime": {"type": "string", "format": "date-time"},
                        "game_id":        {"type": "string"},
                        "notes":          {"type": "string"},
                    },
                }}},
            },
            "responses": {"201": _json_resp("Created", {"type": "object"})},
        },
    }
    paths["/api/schedule/{event_id}"] = {
        "put": {
            "tags": ["schedule"],
            "summary": "Update a scheduled event",
            "parameters": [{"name": "event_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "requestBody": {
                "content": {"application/json": {"schema": {"type": "object"}}}
            },
            "responses": {"200": _json_resp("Updated", _ref("Success"))},
        },
        "delete": {
            "tags": ["schedule"],
            "summary": "Delete a scheduled event",
            "parameters": [{"name": "event_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "responses": {
                "200": _json_resp("Deleted", _ref("Success")),
                "404": _json_resp("Not found", _ref("Error")),
            },
        },
    }

    # ------------------------------------------------------------------
    # Multi-user
    # ------------------------------------------------------------------
    paths["/api/multiuser/common"] = {
        "get": {
            "tags": ["multiuser"],
            "summary": "Find games common to all linked users",
            "responses": {"200": _json_resp("Common games", {"type": "object"})},
        }
    }
    paths["/api/multiuser/pick"] = {
        "post": {
            "tags": ["multiuser"],
            "summary": "Pick a random game owned by all specified users",
            "requestBody": {
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "users":         {"type": "array", "items": {"type": "string"}},
                        "require_coop":  {"type": "boolean"},
                        "filter":        {"type": "string"},
                    },
                }}},
            },
            "responses": {
                "200": _json_resp("Picked game", {"type": "object"}),
                "404": _json_resp("No common games", _ref("Error")),
            },
        }
    }
    paths["/api/multiuser/stats"] = {
        "get": {
            "tags": ["multiuser"],
            "summary": "Playtime statistics across all linked users",
            "responses": {"200": _json_resp("Stats", {"type": "object"})},
        }
    }

    # ------------------------------------------------------------------
    # Voting
    # ------------------------------------------------------------------
    paths["/api/voting/create"] = {
        "post": {
            "tags": ["voting"],
            "summary": "Create a new voting session",
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["candidates"],
                    "properties": {
                        "candidates":    {"type": "array", "items": {"type": "string"},
                                          "minItems": 2},
                        "voting_method": {"type": "string",
                                          "enum": ["plurality", "ranked_choice"],
                                          "default": "plurality"},
                        "duration_mins": {"type": "integer", "default": 60},
                    },
                }}},
            },
            "responses": {
                "201": _json_resp("Session created", _ref("VotingSession")),
            },
        }
    }
    paths["/api/voting/{session_id}/vote"] = {
        "post": {
            "tags": ["voting"],
            "summary": "Cast a vote in a voting session",
            "parameters": [{"name": "session_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {
                        "vote":    {"type": "string",
                                    "description": "Candidate name (plurality sessions)"},
                        "ranking": {"type": "array", "items": {"type": "string"},
                                    "description": "Ordered preference list (ranked-choice sessions)"},
                    },
                }}},
            },
            "responses": {
                "200": _json_resp("Vote recorded", _ref("Success")),
                "400": _json_resp("Invalid vote", _ref("Error")),
                "404": _json_resp("Session not found", _ref("Error")),
            },
        }
    }
    paths["/api/voting/{session_id}/status"] = {
        "get": {
            "tags": ["voting"],
            "summary": "Get current status / vote counts for a session",
            "parameters": [{"name": "session_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "responses": {
                "200": _json_resp("Session status", _ref("VotingSession")),
                "404": _json_resp("Not found", _ref("Error")),
            },
        }
    }
    paths["/api/voting/{session_id}/close"] = {
        "post": {
            "tags": ["voting"],
            "summary": "Close a voting session and determine the winner",
            "parameters": [{"name": "session_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "responses": {
                "200": _json_resp("Result",
                                  {"type": "object",
                                   "properties": {
                                       "winner":         {"type": "string"},
                                       "voting_method":  {"type": "string"},
                                       "irv_rounds":     {"type": "array",
                                                          "items": {"type": "object"},
                                                          "description": "Round-by-round IRV elimination "
                                                                         "(ranked-choice only)"},
                                   }}),
                "404": _json_resp("Not found", _ref("Error")),
            },
        }
    }

    # ------------------------------------------------------------------
    # Budget
    # ------------------------------------------------------------------
    paths["/api/budget"] = {
        "get": {
            "tags": ["budget"],
            "summary": "Get all budget entries and an aggregate summary",
            "responses": {
                "200": _json_resp("Budget summary",
                                  {"type": "object",
                                   "properties": {
                                       "entries":            {"type": "array",
                                                              "items": _ref("BudgetEntry")},
                                       "total_spent":        {"type": "number"},
                                       "primary_currency":   {"type": "string"},
                                       "currency_breakdown": {"type": "object"},
                                       "game_count":         {"type": "integer"},
                                   }}),
            },
        }
    }
    paths["/api/budget/{game_id}"] = {
        "post": {
            "tags": ["budget"],
            "summary": "Record or update the purchase price for a game",
            "parameters": [{"name": "game_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["price"],
                    "properties": {
                        "price":         {"type": "number", "minimum": 0,
                                          "description": "Amount paid; 0 = free/gift"},
                        "currency":      {"type": "string", "default": "USD"},
                        "purchase_date": {"type": "string", "format": "date"},
                        "notes":         {"type": "string"},
                    },
                }}},
            },
            "responses": {
                "200": _json_resp("Saved", _ref("Success")),
                "400": _json_resp("Validation error", _ref("Error")),
            },
        },
        "delete": {
            "tags": ["budget"],
            "summary": "Remove a budget entry",
            "parameters": [{"name": "game_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "responses": {
                "200": _json_resp("Removed", _ref("Success")),
                "404": _json_resp("Not found", _ref("Error")),
            },
        },
    }

    # ------------------------------------------------------------------
    # Wishlist
    # ------------------------------------------------------------------
    paths["/api/wishlist"] = {
        "get": {
            "tags": ["wishlist"],
            "summary": "List all wishlist entries",
            "responses": {
                "200": _json_resp("Wishlist",
                                  {"type": "object",
                                   "properties": {
                                       "entries": {"type": "array", "items": _ref("WishlistEntry")},
                                       "count":   {"type": "integer"},
                                   }}),
            },
        },
        "post": {
            "tags": ["wishlist"],
            "summary": "Add or update a game in the wishlist",
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["game_id", "name"],
                    "properties": {
                        "game_id":      {"type": "string", "example": "steam:620"},
                        "name":         {"type": "string", "example": "Portal 2"},
                        "platform":     {"type": "string", "default": "steam"},
                        "target_price": {"type": "number", "nullable": True,
                                          "description": "Alert when price drops at or below this value"},
                        "notes":        {"type": "string"},
                    },
                }}},
            },
            "responses": {
                "201": _json_resp("Added", _ref("Success")),
                "400": _json_resp("Validation error", _ref("Error")),
            },
        },
    }
    paths["/api/wishlist/{game_id}"] = {
        "delete": {
            "tags": ["wishlist"],
            "summary": "Remove a game from the wishlist",
            "parameters": [{"name": "game_id", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "responses": {
                "200": _json_resp("Removed", _ref("Success")),
                "404": _json_resp("Not found", _ref("Error")),
            },
        }
    }
    paths["/api/wishlist/sales"] = {
        "get": {
            "tags": ["wishlist"],
            "summary": "Check current Steam prices for wishlist items; returns items on sale",
            "description": (
                "Makes live Steam Store API calls for each Steam wishlist entry.  "
                "Returns items where `discount_percent > 0` **or** the current price "
                "is at or below the user-set `target_price`."
            ),
            "responses": {
                "200": _json_resp("Sale results",
                                  {"type": "object",
                                   "properties": {
                                       "sales": {"type": "array",
                                                 "items": {"allOf": [
                                                     _ref("WishlistEntry"),
                                                     {"type": "object",
                                                      "properties": {
                                                          "current_price_usd":  {"type": "number"},
                                                          "original_price_usd": {"type": "number"},
                                                          "discount_percent":   {"type": "integer"},
                                                          "formatted_price":    {"type": "string"},
                                                          "sale_reason":        {"type": "string"},
                                                      }}]}},
                                       "checked":       {"type": "integer"},
                                       "on_sale_count": {"type": "integer"},
                                   }}),
                "503": _json_resp("Steam client not available", _ref("Error")),
            },
        }
    }

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    paths["/api/stats"] = {
        "get": {
            "tags": ["stats"],
            "summary": "Get library statistics (total games, playtime distribution, top played)",
            "responses": {"200": _json_resp("Stats", {"type": "object"})},
        }
    }
    paths["/api/stats/compare"] = {
        "get": {
            "tags": ["stats"],
            "summary": "Compare playtime statistics across linked users",
            "responses": {"200": _json_resp("Comparison", {"type": "object"})},
        }
    }

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    paths["/api/export/library"] = {
        "get": {
            "tags": ["export"],
            "summary": "Export the full game library as CSV",
            "responses": {
                "200": _resp("CSV file",
                              {"text/csv": {"schema": {"type": "string", "format": "binary"}}}),
            },
        }
    }
    paths["/api/export/favorites"] = {
        "get": {
            "tags": ["export"],
            "summary": "Export favourites as CSV",
            "responses": {
                "200": _resp("CSV file",
                              {"text/csv": {"schema": {"type": "string", "format": "binary"}}}),
            },
        }
    }

    # ------------------------------------------------------------------
    # Achievements
    # ------------------------------------------------------------------
    paths["/api/achievements"] = {
        "get": {
            "tags": ["achievements"],
            "summary": "Get achievement completion percentages for all library games",
            "responses": {"200": _json_resp("Achievements", {"type": "object"})},
        }
    }
    paths["/api/achievements/{app_id}"] = {
        "get": {
            "tags": ["achievements"],
            "summary": "Get achievement stats for a specific Steam app",
            "parameters": [{"name": "app_id", "in": "path", "required": True,
                             "schema": {"type": "integer"}}],
            "responses": {
                "200": _json_resp("Achievement stats",
                                  {"type": "object",
                                   "properties": {"total":    {"type": "integer"},
                                                  "achieved": {"type": "integer"},
                                                  "percent":  {"type": "number"}}}),
                "503": _json_resp("Steam client not configured", _ref("Error")),
            },
        }
    }
    paths["/api/achievement-hunt"] = {
        "post": {
            "tags": ["achievements"],
            "summary": "Start an achievement-hunt session for a game",
            "requestBody": {
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "required": ["app_id"],
                    "properties": {"app_id": {"type": "integer"}},
                }}}
            },
            "responses": {"201": _json_resp("Hunt started", {"type": "object"})},
        }
    }

    # ------------------------------------------------------------------
    # Friends
    # ------------------------------------------------------------------
    paths["/api/friends"] = {
        "get": {
            "tags": ["friends"],
            "summary": "Get friends list with their current activity",
            "responses": {"200": _json_resp("Friends", {"type": "object"})},
        }
    }

    # ------------------------------------------------------------------
    # HowLongToBeat
    # ------------------------------------------------------------------
    paths["/api/hltb/{game_name}"] = {
        "get": {
            "tags": ["library"],
            "summary": "Get HowLongToBeat completion times for a game",
            "parameters": [{"name": "game_name", "in": "path", "required": True,
                             "schema": {"type": "string"}}],
            "responses": {
                "200": _json_resp("HLTB data",
                                  {"type": "object",
                                   "properties": {
                                       "main_story": {"type": "number"},
                                       "main_extra": {"type": "number"},
                                       "completionist": {"type": "number"},
                                   }}),
                "503": _json_resp("howlongtobeatpy not installed", _ref("Error")),
            },
        }
    }

    # ------------------------------------------------------------------
    # Duplicates
    # ------------------------------------------------------------------
    paths["/api/duplicates"] = {
        "get": {
            "tags": ["library"],
            "summary": "Detect duplicate games across platforms",
            "responses": {"200": _json_resp("Duplicates", {"type": "object"})},
        }
    }

    # ------------------------------------------------------------------
    # API docs (self-referential)
    # ------------------------------------------------------------------
    paths["/api/openapi.json"] = {
        "get": {
            "tags": ["docs"],
            "summary": "OpenAPI 3.0 specification (JSON)",
            "security": [],
            "responses": {
                "200": _json_resp("OpenAPI spec", {"type": "object"}),
            },
        }
    }
    paths["/api/docs"] = {
        "get": {
            "tags": ["docs"],
            "summary": "Swagger UI — interactive API documentation",
            "security": [],
            "responses": {
                "200": _resp("HTML page",
                              {"text/html": {"schema": {"type": "string"}}}),
            },
        }
    }

    return paths
