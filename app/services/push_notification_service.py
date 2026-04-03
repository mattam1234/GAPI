"""Browser Web Push notification service for GAPI (Phase 11).

Sends W3C Web Push notifications to subscribed browsers using VAPID
(Voluntary Application Server Identification) authentication.

Configuration is read from environment variables:

.. code-block:: text

    VAPID_PRIVATE_KEY   Base64url-encoded EC private key *or* PEM string.
                        Generate with ``PushNotificationService.generate_vapid_keys()``.
    VAPID_PUBLIC_KEY    Base64url-encoded uncompressed EC public key.
                        Must be the companion of VAPID_PRIVATE_KEY.
    VAPID_CLAIMS_EMAIL  ``mailto:`` address included in VAPID JWT claims.
                        Required by most push services.

If ``VAPID_PRIVATE_KEY`` is not set the service silently skips all sends and
returns ``False`` / empty results so the rest of the application continues
normally without any exception.

Dependencies
------------
``pywebpush>=2.3.0`` — install via ``pip install pywebpush``.

If ``pywebpush`` is not installed the service gracefully degrades: all send
methods return ``False`` / empty dicts, ``is_configured()`` returns ``False``,
and a one-time INFO log message is emitted.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency: pywebpush
# ---------------------------------------------------------------------------
try:
    from pywebpush import webpush, WebPushException
    from py_vapid import Vapid
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
        PrivateFormat,
        NoEncryption,
    )
    _HAS_PYWEBPUSH = True
except ImportError:
    _HAS_PYWEBPUSH = False
    logger.info(
        "pywebpush not installed — PushNotificationService is disabled. "
        "Install with: pip install pywebpush"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _b64url_decode(s: str) -> bytes:
    """Decode a URL-safe base64 string with padding tolerance."""
    s = s.strip()
    padding = (4 - len(s) % 4) % 4
    return base64.urlsafe_b64decode(s + '=' * padding)


class PushNotificationService:
    """Send Web Push notifications to subscribed browsers.

    Args:
        private_key_pem:  VAPID EC private key as PEM string.
        public_key_b64:   VAPID public key as base64url string
                          (uncompressed point, 65 bytes).
        claims_email:     Sender contact included in VAPID JWT claims
                          (e.g. ``'mailto:admin@example.com'``).
        timeout:          HTTP request timeout in seconds (default 10).
    """

    def __init__(
        self,
        private_key_pem: Optional[str] = None,
        public_key_b64: Optional[str] = None,
        claims_email: str = 'mailto:admin@gapi.local',
        timeout: int = 10,
    ) -> None:
        self._private_key_pem = private_key_pem or ''
        self._public_key_b64 = public_key_b64 or ''
        self._claims_email = claims_email or 'mailto:admin@gapi.local'
        self._timeout = timeout
        self._vapid: Optional[object] = None   # Vapid instance, lazy-loaded

    # ------------------------------------------------------------------
    # Class-level factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> 'PushNotificationService':
        """Create an instance from environment variables."""
        private_key = os.environ.get('VAPID_PRIVATE_KEY', '')
        public_key = os.environ.get('VAPID_PUBLIC_KEY', '')
        email = os.environ.get('VAPID_CLAIMS_EMAIL', 'mailto:admin@gapi.local')
        # Accept PEM directly or decode from base64url
        if private_key and not private_key.startswith('-----'):
            try:
                pem_bytes = base64.urlsafe_b64decode(
                    private_key + '=' * ((4 - len(private_key) % 4) % 4)
                )
                private_key = pem_bytes.decode('utf-8', errors='replace')
            except Exception:
                pass  # Keep original value; Vapid.from_pem() will reject it
        return cls(
            private_key_pem=private_key,
            public_key_b64=public_key,
            claims_email=email,
        )

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def generate_vapid_keys() -> Dict[str, str]:
        """Generate a new VAPID key-pair.

        Returns a dict with two keys:

        * ``'private_key'``  — PEM-encoded EC private key (store in
          ``VAPID_PRIVATE_KEY``).
        * ``'public_key'``   — base64url-encoded uncompressed EC public key
          (store in ``VAPID_PUBLIC_KEY`` and pass to the browser).

        Raises:
            RuntimeError: when ``pywebpush`` / ``py_vapid`` is not installed.
        """
        if not _HAS_PYWEBPUSH:
            raise RuntimeError(
                "pywebpush is not installed. "
                "Install it with: pip install pywebpush"
            )
        v = Vapid()
        v.generate_keys()
        pub_bytes = v.private_key.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )
        priv_pem = v.private_key.private_bytes(
            Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
        ).decode()
        pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode()
        return {'private_key': priv_pem, 'public_key': pub_b64}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Return ``True`` when VAPID keys are set and pywebpush is installed."""
        return _HAS_PYWEBPUSH and bool(self._private_key_pem)

    def get_public_key(self) -> str:
        """Return the VAPID public key (base64url string) for the browser."""
        return self._public_key_b64

    def _get_vapid(self) -> Optional[object]:
        """Lazy-load and cache the ``Vapid`` instance."""
        if not self.is_configured():
            return None
        if self._vapid is None:
            try:
                self._vapid = Vapid.from_pem(
                    self._private_key_pem.encode()
                    if isinstance(self._private_key_pem, str)
                    else self._private_key_pem
                )
            except Exception as exc:
                logger.error("Failed to load VAPID private key: %s", exc)
                return None
        return self._vapid

    def send_push(
        self,
        subscription_info: Dict[str, object],
        title: str,
        body: str,
        url: str = '/',
        icon: str = '/static/icon-192.png',
        badge: str = '/static/badge-72.png',
    ) -> bool:
        """Send a single Web Push notification to one subscription.

        Args:
            subscription_info: Dict with ``endpoint``, ``keys.p256dh``, and
                               ``keys.auth`` as returned by the browser
                               ``PushSubscription.toJSON()`` call.
            title:  Notification title.
            body:   Notification body text.
            url:    URL to open when the user clicks the notification.
            icon:   Notification icon URL.
            badge:  Small monochrome badge icon URL.

        Returns:
            ``True`` on successful delivery, ``False`` otherwise.
        """
        if not self.is_configured():
            logger.debug("Push notification skipped: service not configured.")
            return False
        vapid = self._get_vapid()
        if vapid is None:
            return False
        import json as _json
        payload = _json.dumps({
            'title': title,
            'body': body,
            'url': url,
            'icon': icon,
            'badge': badge,
        })
        endpoint = subscription_info.get('endpoint', '')
        if not endpoint:
            logger.warning("send_push: missing endpoint in subscription_info")
            return False
        # Derive the audience from the push endpoint URL
        from urllib.parse import urlparse
        parsed = urlparse(endpoint)
        audience = f"{parsed.scheme}://{parsed.netloc}"
        vapid_claims = {
            'sub': self._claims_email,
            'aud': audience,
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=vapid,
                vapid_claims=vapid_claims,
                timeout=self._timeout,
            )
            logger.debug("Push sent to %s…", endpoint[:60])
            return True
        except WebPushException as exc:
            status = getattr(exc.response, 'status_code', None)
            if status in (404, 410):
                # Subscription expired / unregistered
                logger.info(
                    "Push subscription %s… is gone (%s); mark for removal.",
                    endpoint[:60], status,
                )
            else:
                logger.warning("WebPushException for %s…: %s", endpoint[:60], exc)
            return False
        except Exception as exc:
            logger.error("Unexpected error sending push to %s…: %s", endpoint[:60], exc)
            return False

    def send_to_user(
        self,
        db,
        username: str,
        title: str,
        body: str,
        url: str = '/',
        db_module=None,
    ) -> Tuple[int, int]:
        """Send a push notification to all subscriptions of *username*.

        Args:
            db:         SQLAlchemy session.
            username:   Target username.
            title:      Notification title.
            body:       Notification body text.
            url:        URL to open on click.
            db_module:  The ``database`` module (used for subscription
                        retrieval and cleanup of expired endpoints).

        Returns:
            A ``(sent, failed)`` tuple with delivery counts.
        """
        if not self.is_configured() or not db_module:
            return (0, 0)
        subscriptions = db_module.get_user_push_subscriptions(db, username)
        sent = failed = 0
        for sub in subscriptions:
            sub_info = {
                'endpoint': sub['endpoint'],
                'keys': {
                    'p256dh': sub['p256dh'],
                    'auth': sub['auth'],
                },
            }
            ok = self.send_push(sub_info, title, body, url=url)
            if ok:
                sent += 1
            else:
                failed += 1
        return (sent, failed)

    def broadcast(
        self,
        db,
        title: str,
        body: str,
        url: str = '/',
        db_module=None,
        dry_run: bool = False,
    ) -> Dict[str, int]:
        """Send a push notification to **all** opted-in subscribers.

        Args:
            db:       SQLAlchemy session.
            title:    Notification title.
            body:     Notification body.
            url:      URL to open on click.
            db_module: The ``database`` module.
            dry_run:  When ``True`` count subscriptions but do not send.

        Returns:
            Dict with ``total``, ``sent``, ``failed``, ``skipped`` counts.
        """
        if not db_module:
            return {'total': 0, 'sent': 0, 'failed': 0, 'skipped': 0}
        subscriptions = db_module.get_all_push_subscriptions(
            db, push_enabled_only=True
        )
        total = len(subscriptions)
        if dry_run or not self.is_configured():
            return {
                'total': total,
                'sent': 0,
                'failed': 0,
                'skipped': total,
                'dry_run': dry_run,
            }
        sent = failed = 0
        for sub in subscriptions:
            sub_info = {
                'endpoint': sub['endpoint'],
                'keys': {
                    'p256dh': sub['p256dh'],
                    'auth': sub['auth'],
                },
            }
            ok = self.send_push(sub_info, title, body, url=url)
            if ok:
                sent += 1
            else:
                failed += 1
        return {
            'total': total,
            'sent': sent,
            'failed': failed,
            'skipped': 0,
            'dry_run': False,
        }
