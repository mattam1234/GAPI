"""Single-user game pick — the core endpoint (migrated to FastAPI).

Mirrors the legacy Flask ``POST /api/pick`` handler faithfully: advanced
filtering (genre/metacritic/year/platform/device/VR/tag/rarity/collection),
ignored-game exclusion, the random pick, Discord Rich Presence, detail caching,
a background ProtonDB fetch, webhook + WebhookNotifier fan-out, and the pick
audit entry that feeds the analytics dashboard.

All the heavy machinery is reused from ``gapi_gui`` (the per-user picker, the
shared services, the helpers). Error responses use a ``{"error": ...}`` body
(via JSONResponse) to preserve the contract the frontend reads.
"""
import threading
from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

import gapi
import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api", tags=["pick"])


def _err(status_code: int, message: str):
    return JSONResponse(status_code=status_code, content={"error": message})


@router.post("/pick")
def pick_game(body: Optional[dict] = Body(default=None),
              username: str = Depends(require_login)):
    """Pick a random game for the current user."""
    g = gapi_gui
    try:
        g.gui_logger.info("Pick request from user %s", username)
        p = g.ensure_picker_initialized(username)
        if p is None:
            g.gui_logger.warning("Failed to initialize picker for %s", username)
            return _err(500, "Failed to load games")
        if not p.games or len(p.games) == 0:
            g.gui_logger.error("No games available for %s after loading attempt", username)
            return _err(400, "No games available in your library")

        data = body or {}
        filter_type = g._resolve_pick_filter_type(data)
        genre_text = str(data.get("genre", "")).strip()
        genres = [x.strip() for x in genre_text.split(",")] if genre_text else None
        min_metacritic = data.get("min_metacritic")
        min_year = data.get("min_year")
        max_year = data.get("max_year")
        exclude_ids_raw = data.get("exclude_game_ids", "")
        exclude_game_ids = ([s.strip() for s in str(exclude_ids_raw).split(",") if s.strip()]
                            if exclude_ids_raw else None)
        tag_filter = str(data.get("tag", "")).strip() or None
        platform_filter = str(data.get("platform_filter", "")).strip().lower() or None
        device_filter = str(data.get("device_filter", "")).strip().lower() or None
        collection_id = str(data.get("collection_id") or data.get("list_id") or "").strip() or None
        min_rarity = data.get("min_rarity")
        max_rarity = data.get("max_rarity")
        vr_filter_raw = str(data.get("vr_filter", "")).strip().lower() or None
        vr_filter = vr_filter_raw if vr_filter_raw in ("vr_supported", "vr_only", "no_vr") else None

        if g.DB_AVAILABLE:
            db = None
            try:
                db = g.database.SessionLocal()
                if g._ignored_games_service:
                    ignored_games = g._ignored_games_service.get_ignored(db, username)
                else:
                    ignored_games = g.database.get_ignored_games(db, username)
                if ignored_games:
                    if exclude_game_ids:
                        exclude_game_ids.extend(ignored_games)
                    else:
                        exclude_game_ids = ignored_games

                if min_rarity is not None or max_rarity is not None:
                    try:
                        rarity_app_ids = g.database.get_games_with_rare_achievements(
                            db, username,
                            max_rarity=float(max_rarity) if max_rarity is not None else 100.0,
                            min_rarity=float(min_rarity) if min_rarity is not None else 0.0,
                        )
                        if rarity_app_ids:
                            rarity_set = set(str(aid) for aid in rarity_app_ids)
                            extra_excludes = [
                                str(gm.get("appid", gm.get("id", "")))
                                for gm in p.games
                                if str(gm.get("appid", gm.get("id", ""))) not in rarity_set
                            ]
                            if exclude_game_ids:
                                exclude_game_ids.extend(extra_excludes)
                            else:
                                exclude_game_ids = extra_excludes
                        else:
                            g.gui_logger.info(
                                "No games found matching rarity filter [%s, %s] for %s",
                                min_rarity, max_rarity, username)
                    except Exception as e:
                        g.gui_logger.warning("Could not apply rarity filter: %s", e)
            except Exception as e:
                g.gui_logger.warning("Could not fetch ignored games: %s", e)
            finally:
                if db:
                    try:
                        db.close()
                    except Exception:
                        pass

        adv = {
            "genres": genres,
            "min_metacritic": int(min_metacritic) if min_metacritic is not None else None,
            "min_release_year": int(min_year) if min_year is not None else None,
            "max_release_year": int(max_year) if max_year is not None else None,
            "exclude_game_ids": exclude_game_ids,
            "platforms": [platform_filter] if platform_filter else None,
            "device_types": [device_filter] if device_filter else None,
            "vr_filter": vr_filter,
        }

        with g.picker_lock:
            try:
                filtered_games = None
                if filter_type == "unplayed":
                    filtered_games = p.filter_games(max_playtime=0, **adv)
                elif filter_type == "barely":
                    filtered_games = p.filter_games(
                        max_playtime=p.BARELY_PLAYED_THRESHOLD_MINUTES, **adv)
                elif filter_type == "well":
                    filtered_games = p.filter_games(
                        min_playtime=p.WELL_PLAYED_THRESHOLD_MINUTES, **adv)
                elif filter_type == "favorites":
                    filtered_games = p.filter_games(favorites_only=True, **adv)
                elif any(v is not None and v != [] for v in adv.values()):
                    filtered_games = p.filter_games(**adv)

                if tag_filter:
                    filtered_games = p.tag_service.filter_by_tag(
                        tag_filter,
                        filtered_games if filtered_games is not None else p.games)

                if platform_filter or device_filter:
                    base_games = filtered_games if filtered_games is not None else p.games
                    filtered_games = g._filter_games_by_platform_device(
                        base_games, platform_filter, device_filter)

                if collection_id:
                    backlog_service = g._get_shared_backlog_service()
                    resolved_collection_id = backlog_service.resolve_collection_for_user(
                        collection_id, username)
                    collection_games = backlog_service.get_games(
                        p.games, username=username, collection_id=resolved_collection_id)
                    allowed_tokens = {
                        token for backlog_game in collection_games
                        for token in g._game_identity_tokens(backlog_game)}
                    base_games = filtered_games if filtered_games is not None else p.games
                    filtered_games = [
                        gm for gm in base_games
                        if g._game_identity_tokens(gm) & allowed_tokens]

                if filtered_games is not None and len(filtered_games) == 0:
                    g.gui_logger.info("No games matched filters for %s", username)
                    return _err(400, "No games match the selected filters")

                game = p.pick_random_game(filtered_games)
                if not game:
                    g.gui_logger.error("Failed to pick game for %s", username)
                    return _err(500, "Failed to pick a game")

                g.current_game = game
                g.gui_logger.info("Picked game for %s: %s", username, game.get("name"))

                app_id = game.get("appid")
                game_id = game.get("game_id") or (f"steam:{app_id}" if app_id else None)
                name = game.get("name", "Unknown Game")
                playtime_hours = game.get("playtime_forever", 0) / 60

                if g._discord_rpc and g._discord_rpc.enabled:
                    g._discord_rpc.update(name, playtime_hours=playtime_hours)

                is_favorite = app_id in p.favorites if app_id else False
                review = p.review_service.get(game_id) if game_id else None
                tags = p.tag_service.get(game_id) if game_id else []
                backlog_status = None
                if game_id:
                    try:
                        backlog_status = g._get_shared_backlog_service().get_status(
                            game_id, username=username)
                    except Exception:
                        backlog_status = p.backlog_service.get_status(game_id)

                response = {
                    "app_id": app_id, "game_id": game_id, "name": name,
                    "playtime_hours": round(playtime_hours, 1),
                    "is_favorite": is_favorite, "review": review, "tags": tags,
                    "backlog_status": backlog_status,
                    "steam_url": f"https://store.steampowered.com/app/{app_id}/",
                    "steamdb_url": f"https://steamdb.info/app/{app_id}/",
                }

                try:
                    if app_id and p.steam_client:
                        details = p.steam_client.get_game_details(app_id)
                        if details:
                            if "short_description" in details:
                                response["description"] = details["short_description"]
                            if "header_image" in details:
                                response["header_image"] = details["header_image"]
                            if "capsule_image" in details:
                                response["capsule_image"] = details["capsule_image"]
                            if "genres" in details:
                                response["genres"] = [x["description"] for x in details["genres"]]
                            if "release_date" in details:
                                response["release_date"] = details["release_date"].get("date", "")
                            if "metacritic" in details:
                                response["metacritic_score"] = details["metacritic"].get("score")

                            try:
                                if g.DB_AVAILABLE and g.ensure_db_available():
                                    db = None
                                    try:
                                        db = g.database.SessionLocal()
                                        platform = game.get("platform", "steam")
                                        if g._library_service:
                                            g._library_service.update_game_details(
                                                db, app_id, platform, response)
                                        else:
                                            g.database.update_game_details_cache(
                                                db, app_id, platform, response)
                                    except Exception as cache_err:
                                        g.gui_logger.debug("Failed to cache details: %s", cache_err)
                                    finally:
                                        if db:
                                            db.close()
                            except Exception as e:
                                g.gui_logger.debug("Failed to cache game details: %s", e)

                            def fetch_protondb(_p=p, _app_id=app_id):
                                try:
                                    if _p.steam_client:
                                        protondb = _p.steam_client.get_protondb_rating(_app_id)
                                        if protondb:
                                            response["protondb"] = protondb
                                except Exception:
                                    pass

                            threading.Thread(target=fetch_protondb, daemon=True).start()
                except Exception as e:
                    g.gui_logger.debug("Failed to fetch game details: %s", e)

                webhook_url = p.config.get("webhook_url", "").strip() if p.config else ""
                if webhook_url and not gapi.is_placeholder_value(webhook_url):
                    wh_payload = {
                        "content": f"🎮 **Game pick:** {name} ({round(playtime_hours, 1)}h played)\n"
                                   f"{response.get('steam_url', '')}",
                        "game": response,
                    }
                    threading.Thread(target=gapi.send_webhook,
                                     args=(webhook_url, wh_payload), daemon=True).start()

                try:
                    from webhook_notifier import WebhookNotifier
                    _notifier = WebhookNotifier(p.config or {})
                    _has_extra = any(_notifier._get(k) for k in (
                        "slack_webhook_url", "teams_webhook_url",
                        "ifttt_webhook_key", "homeassistant_url"))
                    if _has_extra:
                        threading.Thread(target=_notifier.notify_game_picked,
                                         args=(response,), daemon=True).start()
                except Exception as _wh_exc:
                    g.gui_logger.debug("WebhookNotifier error: %s", _wh_exc)

                g._audit(
                    "pick", resource_type="game",
                    resource_id=str(game_id) if game_id else (str(app_id) if app_id else None),
                    description=name, actor=username,
                )
                return response

            except Exception as e:
                g.gui_logger.exception("Error in pick endpoint for %s: %s", username, e)
                return _err(500, f"Error picking game: {str(e)}")
    except Exception as e:
        g.gui_logger.exception("Unexpected error in pick endpoint: %s", e)
        return _err(500, f"Unexpected error: {str(e)}")
