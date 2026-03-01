"""
webhook_notifier.py
===================
Dispatch game-pick events (and other GAPI notifications) to external
notification services:

* **Slack** — Incoming Webhook with Block Kit formatting
* **Microsoft Teams** — Incoming Webhook with an Adaptive Card
* **IFTTT** — Maker Webhooks channel (triggers a named event)
* **Home Assistant** — REST API webhook trigger

All methods are *fire-and-forget* (non-blocking); they perform the HTTP
request in the calling thread and swallow non-fatal errors to avoid
disrupting the main application.

Configuration
-------------
Add any combination of these keys to ``config.json``::

    "slack_webhook_url":      "https://hooks.slack.com/services/T.../B.../...",
    "teams_webhook_url":      "https://...webhook.office.com/webhookb2/...",
    "ifttt_webhook_key":      "YOUR_IFTTT_KEY",
    "ifttt_event_name":       "gapi_game_picked",
    "homeassistant_url":      "http://homeassistant.local:8123",
    "homeassistant_token":    "Bearer eyJ...",
    "homeassistant_webhook_id": "gapi_game_picked"

Usage
-----
::

    from webhook_notifier import WebhookNotifier

    notifier = WebhookNotifier(config)
    notifier.notify_game_picked(game_dict)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 8  # seconds


class WebhookNotifier:
    """Dispatch game-pick notifications to one or more external services.

    Args:
        config: The application configuration dict (from ``config.json``).
        timeout: HTTP request timeout in seconds.
    """

    def __init__(self, config: Dict[str, Any], timeout: int = _DEFAULT_TIMEOUT) -> None:
        self._cfg     = config or {}
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def notify_game_picked(self, game: Dict[str, Any]) -> Dict[str, bool]:
        """Fire notifications to every configured service.

        Args:
            game: The picked-game dict as returned by the ``/api/pick`` endpoint.
                  Must contain at least ``name`` (str).

        Returns:
            A ``{service: success}`` dict, e.g.
            ``{"slack": True, "teams": False, "ifttt": True, "homeassistant": True}``.
        """
        results: Dict[str, bool] = {}

        slack_url = self._get('slack_webhook_url')
        if slack_url:
            results['slack'] = self.send_slack(slack_url, game)

        teams_url = self._get('teams_webhook_url')
        if teams_url:
            results['teams'] = self.send_teams(teams_url, game)

        ifttt_key = self._get('ifttt_webhook_key')
        if ifttt_key:
            event = self._cfg.get('ifttt_event_name', 'gapi_game_picked')
            results['ifttt'] = self.send_ifttt(ifttt_key, event, game)

        ha_url   = self._get('homeassistant_url')
        ha_token = self._get('homeassistant_token')
        ha_id    = self._get('homeassistant_webhook_id')
        if ha_url and ha_id:
            results['homeassistant'] = self.send_homeassistant(
                ha_url, ha_id, game, token=ha_token
            )

        return results

    def send_slack(self, webhook_url: str, game: Dict[str, Any]) -> bool:
        """Send a Slack Incoming Webhook message with Block Kit formatting.

        Produces a two-block message: a header and a details section that
        includes playtime, store link, and a game thumbnail.

        Args:
            webhook_url: Slack Incoming Webhook URL.
            game:        Game dict (must include ``name``; optional:
                         ``playtime_hours``, ``steam_url``, ``header_image``).

        Returns:
            ``True`` on a 2xx response, ``False`` otherwise.
        """
        name    = game.get('name', 'Unknown game')
        hours   = game.get('playtime_hours', game.get('playtime_forever', 0) / 60)
        url     = game.get('steam_url', '')
        img_url = game.get('header_image') or game.get('capsule_image', '')

        header_text = f":joystick: *GAPI picked:* {name}"
        detail_lines = [f"• Playtime: *{round(hours, 1)}h*"]
        if url:
            detail_lines.append(f"• <{url}|View on Steam>")

        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": header_text},
            }
        ]
        if img_url:
            blocks[0]["accessory"] = {
                "type": "image",
                "image_url": img_url,
                "alt_text": name,
            }
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(detail_lines)},
        })

        payload = {
            "text": f"🎮 GAPI picked: {name}",  # fallback for notifications
            "blocks": blocks,
        }
        return self._post(webhook_url, payload)

    def send_teams(self, webhook_url: str, game: Dict[str, Any]) -> bool:
        """Send a Microsoft Teams Incoming Webhook message (Adaptive Card).

        Args:
            webhook_url: Teams channel Incoming Webhook URL.
            game:        Game dict.

        Returns:
            ``True`` on a 2xx response, ``False`` otherwise.
        """
        name    = game.get('name', 'Unknown game')
        hours   = game.get('playtime_hours', game.get('playtime_forever', 0) / 60)
        url     = game.get('steam_url', '')
        img_url = game.get('header_image') or game.get('capsule_image', '')

        body_items: list = [
            {
                "type": "TextBlock",
                "text": f"🎮 GAPI picked: **{name}**",
                "size": "Large",
                "weight": "Bolder",
            },
            {
                "type": "TextBlock",
                "text": f"Playtime: {round(hours, 1)}h",
                "isSubtle": True,
            },
        ]
        if img_url:
            body_items.insert(0, {
                "type": "Image",
                "url": img_url,
                "altText": name,
            })

        actions = []
        if url:
            actions.append({
                "type": "Action.OpenUrl",
                "title": "View on Steam",
                "url": url,
            })

        adaptive_card: Dict[str, Any] = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": body_items,
        }
        if actions:
            adaptive_card["actions"] = actions

        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": adaptive_card,
                }
            ],
        }
        return self._post(webhook_url, payload)

    @staticmethod
    def send_ifttt(
        webhook_key: str,
        event_name: str,
        game: Dict[str, Any],
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> bool:
        """Trigger an IFTTT Maker Webhooks event.

        The ``value1`` field carries the game name, ``value2`` the playtime
        (hours), and ``value3`` the Steam store URL.

        Args:
            webhook_key: IFTTT Maker Webhooks key.
            event_name:  Event name (e.g. ``"gapi_game_picked"``).
            game:        Game dict.
            timeout:     Request timeout in seconds.

        Returns:
            ``True`` on a 2xx response, ``False`` otherwise.
        """
        name  = game.get('name', 'Unknown game')
        hours = game.get('playtime_hours', game.get('playtime_forever', 0) / 60)
        url   = game.get('steam_url', '')

        endpoint = (
            f"https://maker.ifttt.com/trigger/{event_name}"
            f"/with/key/{webhook_key}"
        )
        payload = {
            "value1": name,
            "value2": str(round(hours, 1)),
            "value3": url,
        }
        try:
            resp = requests.post(endpoint, json=payload, timeout=timeout)
            resp.raise_for_status()
            logger.info("IFTTT event '%s' triggered (HTTP %s)", event_name, resp.status_code)
            return True
        except requests.RequestException as exc:
            logger.warning("IFTTT delivery failed: %s", exc)
            return False

    @staticmethod
    def send_homeassistant(
        base_url: str,
        webhook_id: str,
        game: Dict[str, Any],
        token: Optional[str] = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> bool:
        """Trigger a Home Assistant webhook.

        Sends a POST to ``{base_url}/api/webhook/{webhook_id}`` with the game
        data as JSON.  If *token* is provided it is sent as a Long-Lived
        Access Token (Authorization header) to support authenticated webhooks.

        Args:
            base_url:   Home Assistant instance URL (no trailing slash),
                        e.g. ``"http://homeassistant.local:8123"``.
            webhook_id: Webhook ID configured in Home Assistant,
                        e.g. ``"gapi_game_picked"``.
            game:       Game dict to include in the POST body.
            token:      Optional long-lived access token (Bearer format).
            timeout:    Request timeout in seconds.

        Returns:
            ``True`` on a 2xx response, ``False`` otherwise.
        """
        endpoint = f"{base_url.rstrip('/')}/api/webhook/{webhook_id}"
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if token:
            # Strip "Bearer " prefix if accidentally included in config
            raw = token.strip()
            if not raw.lower().startswith("bearer "):
                raw = f"Bearer {raw}"
            headers["Authorization"] = raw

        payload = {
            "game_name":    game.get('name', 'Unknown'),
            "playtime_hours": round(
                game.get('playtime_hours', game.get('playtime_forever', 0) / 60), 1
            ),
            "appid":        game.get('appid', ''),
            "steam_url":    game.get('steam_url', ''),
        }
        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            logger.info(
                "Home Assistant webhook '%s' triggered (HTTP %s)",
                webhook_id, resp.status_code,
            )
            return True
        except requests.RequestException as exc:
            logger.warning("Home Assistant delivery failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, key: str) -> str:
        """Return a config value, or empty string if absent / placeholder."""
        val = self._cfg.get(key, '')
        if not val or not isinstance(val, str):
            return ''
        if val.startswith('YOUR_') or not val.strip():
            return ''
        return val.strip()

    def _post(self, url: str, payload: Dict[str, Any]) -> bool:
        try:
            resp = requests.post(url, json=payload, timeout=self._timeout)
            resp.raise_for_status()
            logger.info("Webhook delivered to %s (HTTP %s)", url, resp.status_code)
            return True
        except requests.RequestException as exc:
            logger.warning("Webhook delivery failed (%s): %s", url, exc)
            return False
