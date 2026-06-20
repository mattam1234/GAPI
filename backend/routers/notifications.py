"""Notification preferences + history domain (migrated to FastAPI).

Mirrors the legacy Flask routes:
  * GET  /api/notifications/preferences
  * PUT  /api/notifications/preferences
  * GET  /api/notifications/history
  * GET  /api/notifications/mock
  * GET  /api/notifications
  * POST /api/notifications/read
  * POST /api/notifications/send
  * POST /api/notifications/slack/test
  * POST /api/notifications/teams/test
  * POST /api/notifications/ifttt/test
  * POST /api/notifications/homeassistant/test

DB-backed via the legacy ``database`` notification helpers. Preferences return
503 when the DB is down; history degrades to an empty page (200).

The list/read/send routes reuse the legacy ``_notification_service`` singleton
on ``gapi_gui`` (referenced at CALL TIME). The slack/teams/ifttt/homeassistant
``/test`` routes build a ``WebhookNotifier`` from the current picker config and
fire outbound webhook calls.

The legacy ``after_request`` set ``Cache-Control: no-store`` on every ``/api/*``
response (notifications is not in the cacheable-prefix allowlist); that header
is set explicitly here via the JSONResponse helpers to preserve behaviour.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

import gapi_gui
from backend.dependencies import require_login

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

_NO_STORE = {"Cache-Control": "no-store"}


def _err(status_code, message):
    return JSONResponse(status_code=status_code, content={"error": message},
                        headers=_NO_STORE)


def _ok(content, status_code=200):
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE)


@router.get("/preferences")
def get_preferences(username: str = Depends(require_login)):
    """Return the current user's notification preferences."""
    if not gapi_gui.DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        db = next(gapi_gui.database.get_db())
        return gapi_gui.database.get_notification_prefs(db, username)
    except Exception as e:
        gapi_gui.gui_logger.error("get_preferences error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/preferences")
def set_preferences(body: Optional[dict] = Body(default=None),
                    username: str = Depends(require_login)):
    """Update the current user's notification preferences."""
    if not gapi_gui.DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    data = body or {}
    try:
        db = next(gapi_gui.database.get_db())
        updated = gapi_gui.database.set_notification_prefs(db, username, data)
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to save preferences")
        return updated
    except HTTPException:
        raise
    except Exception as e:
        gapi_gui.gui_logger.error("set_preferences error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
def history(request: Request, username: str = Depends(require_login)):
    """Return paginated notification history for the current user."""
    if not gapi_gui.DB_AVAILABLE:
        return {"notifications": [], "total": 0}
    args = request.query_params
    try:
        limit = max(1, min(200, int(args.get("limit", 50))))
    except (ValueError, TypeError):
        limit = 50
    try:
        offset = max(0, int(args.get("offset", 0)))
    except (ValueError, TypeError):
        offset = 0
    unread_only = str(args.get("unread", "")).lower() in ("true", "1", "yes")
    try:
        db = next(gapi_gui.database.get_db())
        notifications = gapi_gui.database.get_notifications(
            db, username, unread_only=unread_only)
        total = len(notifications)
        page = notifications[offset: offset + limit]
        return {"notifications": page, "total": total}
    except Exception as e:
        gapi_gui.gui_logger.error("history error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mock")
def api_get_notifications_mock(username: str = Depends(require_login)):
    """Return user notifications (dev/demo mock data)."""
    notifications = [
        {'id': '1', 'type': 'mentions', 'title': 'You were mentioned',
         'message': '@user mentioned you in general chat', 'unread': True,
         'created_at': datetime.now().isoformat()},
        {'id': '2', 'type': 'invites', 'title': 'Session Invite',
         'message': 'You were invited to Game Night session', 'unread': True,
         'created_at': datetime.now().isoformat()},
        {'id': '3', 'type': 'picks', 'title': 'Game Picked',
         'message': 'Portal 2 was picked in your recent session', 'unread': False,
         'created_at': (datetime.now().isoformat())},
    ]
    return _ok({'notifications': notifications})


@router.get("")
def api_get_notifications(request: Request, username: str = Depends(require_login)):
    """Return notifications for the current user.

    Query params:
      - ``unread_only``: 'true' to return only unread (default false)
    """
    unread_only = request.query_params.get('unread_only', 'false').lower() == 'true'
    db = next(gapi_gui.database.get_db())
    try:
        if gapi_gui._notification_service:
            notifs = gapi_gui._notification_service.get_all(
                db, username, unread_only=unread_only)
        else:
            notifs = gapi_gui.database.get_notifications(
                db, username, unread_only=unread_only)
    finally:
        if db:
            db.close()
    return _ok({'notifications': notifs,
                'unread_count': sum(1 for n in notifs if not n['is_read'])})


@router.post("/read")
def api_mark_notifications_read(body: Optional[dict] = Body(default=None),
                                username: str = Depends(require_login)):
    """Mark notifications as read.

    Request JSON (optional):
      - ``ids``: list of notification IDs. If omitted, marks all as read.
    """
    data = body or {}
    ids = data.get('ids')
    db = next(gapi_gui.database.get_db())
    try:
        if gapi_gui._notification_service:
            ok = gapi_gui._notification_service.mark_read(db, username, ids=ids)
        else:
            ok = gapi_gui.database.mark_notifications_read(
                db, username, notification_ids=ids)
    finally:
        if db:
            db.close()
    if ok:
        return _ok({'success': True})
    return _err(500, 'Failed to mark notifications read')


@router.post("/send")
def api_send_notification(body: Optional[dict] = Body(default=None),
                          sender: str = Depends(require_login)):
    """Send a notification to a user (admin only).

    Request JSON:
      - ``username``: target username (required)
      - ``title``:    notification title (required)
      - ``message``:  notification message (required)
      - ``type``:     'info' | 'warning' | 'success' | 'error' (default 'info')
    """
    # Only admins can send notifications to others
    db_check = next(gapi_gui.database.get_db())
    try:
        if gapi_gui._notification_service:
            is_admin = gapi_gui._notification_service.is_admin(db_check, sender)
        else:
            is_admin = 'admin' in gapi_gui.database.get_user_roles(db_check, sender)
    finally:
        if db_check:
            db_check.close()
    if not is_admin:
        return _err(403, 'Admin access required')
    data = body or {}
    username = data.get('username', '').strip()
    title = data.get('title', '').strip()
    message = data.get('message', '').strip()
    notif_type = data.get('type', 'info')
    if not username or not title or not message:
        return _err(400, 'username, title, and message are required')
    db = next(gapi_gui.database.get_db())
    try:
        if gapi_gui._notification_service:
            ok = gapi_gui._notification_service.create(
                db, username, title, message, notif_type=notif_type)
        else:
            ok = gapi_gui.database.create_notification(
                db, username, title, message, type=notif_type)
    finally:
        if db:
            db.close()
    if ok:
        return _ok({'success': True})
    return _err(500, 'Failed to send notification')


_TEST_GAME = {
    'name': 'GAPI Test Notification',
    'playtime_hours': 0.0,
    'steam_url': 'https://store.steampowered.com',
}


@router.post("/slack/test")
def api_test_slack_webhook(body: Optional[dict] = Body(default=None),
                           username: str = Depends(require_login)):
    """Send a test notification to the configured Slack Incoming Webhook."""
    from webhook_notifier import WebhookNotifier
    data = body or {}
    cfg = dict((gapi_gui.picker.config if gapi_gui.picker else {}) or {})
    override = data.get('webhook_url', '')
    if override:
        cfg['slack_webhook_url'] = override
    notifier = WebhookNotifier(cfg)
    slack_url = notifier._get('slack_webhook_url')
    if not slack_url:
        return _err(503, (
            'Slack webhook URL not configured. '
            'Add slack_webhook_url to config.json or supply it in the request body.'
        ))
    ok = notifier.send_slack(slack_url, _TEST_GAME)
    return _ok({'success': ok, 'service': 'slack'})


@router.post("/teams/test")
def api_test_teams_webhook(body: Optional[dict] = Body(default=None),
                           username: str = Depends(require_login)):
    """Send a test notification to the configured Microsoft Teams Incoming Webhook."""
    from webhook_notifier import WebhookNotifier
    data = body or {}
    cfg = dict((gapi_gui.picker.config if gapi_gui.picker else {}) or {})
    override = data.get('webhook_url', '')
    if override:
        cfg['teams_webhook_url'] = override
    notifier = WebhookNotifier(cfg)
    teams_url = notifier._get('teams_webhook_url')
    if not teams_url:
        return _err(503, (
            'Teams webhook URL not configured. '
            'Add teams_webhook_url to config.json or supply it in the request body.'
        ))
    ok = notifier.send_teams(teams_url, _TEST_GAME)
    return _ok({'success': ok, 'service': 'teams'})


@router.post("/ifttt/test")
def api_test_ifttt_webhook(body: Optional[dict] = Body(default=None),
                           username: str = Depends(require_login)):
    """Send a test event to the configured IFTTT Maker Webhooks channel."""
    from webhook_notifier import WebhookNotifier
    data = body or {}
    cfg = dict((gapi_gui.picker.config if gapi_gui.picker else {}) or {})
    if data.get('ifttt_webhook_key'):
        cfg['ifttt_webhook_key'] = data['ifttt_webhook_key']
    if data.get('ifttt_event_name'):
        cfg['ifttt_event_name'] = data['ifttt_event_name']
    notifier = WebhookNotifier(cfg)
    key = notifier._get('ifttt_webhook_key')
    if not key:
        return _err(503, (
            'IFTTT webhook key not configured. '
            'Add ifttt_webhook_key to config.json or supply it in the request body.'
        ))
    event = cfg.get('ifttt_event_name', 'gapi_game_picked')
    ok = WebhookNotifier.send_ifttt(key, event, _TEST_GAME)
    return _ok({'success': ok, 'service': 'ifttt'})


@router.post("/homeassistant/test")
def api_test_homeassistant_webhook(body: Optional[dict] = Body(default=None),
                                   username: str = Depends(require_login)):
    """Send a test event to the configured Home Assistant webhook."""
    from webhook_notifier import WebhookNotifier
    data = body or {}
    cfg = dict((gapi_gui.picker.config if gapi_gui.picker else {}) or {})
    for key in ('homeassistant_url', 'homeassistant_webhook_id', 'homeassistant_token'):
        if data.get(key):
            cfg[key] = data[key]
    notifier = WebhookNotifier(cfg)
    ha_url = notifier._get('homeassistant_url')
    ha_id = notifier._get('homeassistant_webhook_id')
    if not ha_url or not ha_id:
        return _err(503, (
            'Home Assistant URL and webhook ID must be configured. '
            'Add homeassistant_url and homeassistant_webhook_id to config.json '
            'or supply them in the request body.'
        ))
    ha_token = notifier._get('homeassistant_token')
    ok = WebhookNotifier.send_homeassistant(ha_url, ha_id, _TEST_GAME, token=ha_token)
    return _ok({'success': ok, 'service': 'homeassistant'})
