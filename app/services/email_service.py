"""SMTP-based email notification service for GAPI.

Sends transactional email notifications to users who have opted in via their
notification preferences (``email_enabled = True``).

Configuration is read from environment variables:

.. code-block:: text

    SMTP_HOST      SMTP server hostname (default: localhost)
    SMTP_PORT      SMTP port (default: 587)
    SMTP_USER      SMTP authentication username (optional)
    SMTP_PASSWORD  SMTP authentication password (optional)
    SMTP_FROM      Sender address (default: noreply@gapi.local)
    SMTP_USE_TLS   Whether to use STARTTLS (default: true)
    SMTP_USE_SSL   Whether to use SMTPS/SSL (default: false)

If ``SMTP_HOST`` is not set the service silently skips all sends and returns
``False`` from every method so the rest of the application continues normally.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


def _is_valid_email(address: str) -> bool:
    """Return ``True`` if *address* looks like a valid email address.

    Uses :func:`email.utils.parseaddr` to extract the address component, then
    verifies it contains exactly one ``@`` with non-empty local and domain
    parts, and a domain containing at least one ``.``.
    """
    if not address or not isinstance(address, str):
        return False
    _, addr = parseaddr(address.strip())
    if not addr or addr.count('@') != 1:
        return False
    local, domain = addr.split('@', 1)
    return bool(local) and '.' in domain and not domain.startswith('.')


class EmailService:
    """Send transactional emails using SMTP.

    Args:
        host:       SMTP server hostname.  If ``None`` or empty the service
                    is disabled and all send methods return ``False``.
        port:       SMTP port (default 587 for STARTTLS).
        username:   SMTP auth username (optional).
        password:   SMTP auth password (optional).
        sender:     Envelope / ``From`` address.
        use_tls:    Use STARTTLS upgrade on the connection (default ``True``).
        use_ssl:    Wrap the entire connection in SSL/TLS (default ``False``).
                    When ``True``, *use_tls* is ignored.
        timeout:    Connection timeout in seconds (default 10).
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: int = 587,
        username: Optional[str] = None,
        password: Optional[str] = None,
        sender: str = 'noreply@gapi.local',
        use_tls: bool = True,
        use_ssl: bool = False,
        timeout: int = 10,
    ) -> None:
        self._host     = host or ''
        self._port     = port
        self._username = username or ''
        self._password = password or ''
        self._sender   = sender
        self._use_tls  = use_tls
        self._use_ssl  = use_ssl
        self._timeout  = timeout

    # ------------------------------------------------------------------
    # Class-level factory — reads configuration from environment
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> 'EmailService':
        """Create an :class:`EmailService` instance from environment variables.

        Returns:
            Configured service (may be disabled if ``SMTP_HOST`` is not set).
        """
        host     = os.environ.get('SMTP_HOST', '').strip()
        port_str = os.environ.get('SMTP_PORT', '587').strip()
        username = os.environ.get('SMTP_USER', '').strip()
        password = os.environ.get('SMTP_PASSWORD', '').strip()
        sender   = os.environ.get('SMTP_FROM', 'noreply@gapi.local').strip()
        use_tls  = os.environ.get('SMTP_USE_TLS', 'true').lower() not in ('0', 'false', 'no')
        use_ssl  = os.environ.get('SMTP_USE_SSL', 'false').lower() in ('1', 'true', 'yes')
        try:
            port = int(port_str)
        except (ValueError, TypeError):
            port = 587
        return cls(
            host=host,
            port=port,
            username=username or None,
            password=password or None,
            sender=sender,
            use_tls=use_tls,
            use_ssl=use_ssl,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Return ``True`` if SMTP is configured (``SMTP_HOST`` is non-empty)."""
        return bool(self._host)

    def config_info(self) -> dict:
        """Return a dict of public (non-secret) configuration values.

        Returns:
            Dict with ``configured``, ``sender``, ``host``, ``port``,
            ``use_tls``, ``use_ssl`` keys.  Credentials (username / password)
            are intentionally excluded.
        """
        return {
            'configured': self.is_configured(),
            'sender':     self._sender if self.is_configured() else '',
            'host':       self._host,
            'port':       self._port,
            'use_tls':    self._use_tls,
            'use_ssl':    self._use_ssl,
        }

    def send_email(
        self,
        to_address: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
    ) -> bool:
        """Send a single email.

        Args:
            to_address: Recipient email address.
            subject:    Email subject line.
            body:       Plain-text body (always included as a fallback).
            html_body:  Optional HTML body. When provided, a
                        ``multipart/alternative`` message is constructed so
                        mail clients prefer the HTML version.

        Returns:
            ``True`` on success, ``False`` if not configured or on error.
        """
        if not self.is_configured():
            logger.debug('EmailService: SMTP not configured — skipping send to %s', to_address)
            return False
        if not _is_valid_email(to_address):
            logger.warning('EmailService: invalid to_address %r — skipping', to_address)
            return False

        msg = self._build_message(to_address, subject, body, html_body)
        try:
            self._send(msg, [to_address])
            logger.info('EmailService: sent "%s" to %s', subject, to_address)
            return True
        except Exception as exc:
            logger.error('EmailService: failed to send "%s" to %s: %s', subject, to_address, exc)
            return False

    def send_notification_email(
        self,
        to_address: str,
        username: str,
        notification: Dict,
    ) -> bool:
        """Send a single notification as an email.

        Args:
            to_address:   Recipient email address.
            username:     Recipient's GAPI username (used in body text).
            notification: Notification dict with keys ``title`` and ``message``
                          (as returned by the database notification helpers).

        Returns:
            ``True`` on success, ``False`` on error or if not configured.
        """
        title   = notification.get('title', 'GAPI Notification')
        message = notification.get('message', '')
        subject = f'[GAPI] {title}'
        body    = (
            f'Hi {username},\n\n'
            f'{message}\n\n'
            '— The GAPI Team\n'
            'You are receiving this because you have email notifications enabled.\n'
            'To unsubscribe, visit your notification preferences in the GAPI app.'
        )
        html_body = (
            f'<p>Hi <strong>{username}</strong>,</p>'
            f'<p>{message}</p>'
            '<hr>'
            '<p style="font-size:0.85em;color:#666;">'
            'You are receiving this because you have email notifications enabled. '
            'To unsubscribe, visit your <em>notification preferences</em> in the GAPI app.'
            '</p>'
        )
        return self.send_email(to_address, subject, body, html_body)

    def send_digest_email(
        self,
        to_address: str,
        username: str,
        notifications: Sequence[Dict],
        period: str = 'daily',
    ) -> bool:
        """Send a digest of multiple notifications in one email.

        Args:
            to_address:    Recipient email address.
            username:      Recipient's GAPI username.
            notifications: List of unread notification dicts (each with
                           ``title`` and ``message`` keys).
            period:        ``'daily'`` or ``'weekly'`` — used in the subject.

        Returns:
            ``True`` on success, ``False`` on error or if not configured.
        """
        if not notifications:
            logger.debug('EmailService: no notifications for digest to %s', to_address)
            return False

        count   = len(notifications)
        period_label = period.capitalize()
        subject = f'[GAPI] Your {period_label} Digest — {count} new notification{"s" if count != 1 else ""}'

        lines = [f'Hi {username},\n', f'You have {count} new notification{"s" if count != 1 else ""}:\n']
        html_lines = [
            f'<p>Hi <strong>{username}</strong>,</p>',
            f'<p>You have <strong>{count}</strong> new notification{"s" if count != 1 else ""}:</p>',
            '<ul>',
        ]
        for notif in notifications:
            title   = notif.get('title', 'Notification')
            message = notif.get('message', '')
            lines.append(f'• {title}: {message}')
            html_lines.append(f'<li><strong>{title}</strong>: {message}</li>')

        html_lines.append('</ul>')
        lines.append('\n— The GAPI Team')
        html_lines.extend([
            '<hr>',
            '<p style="font-size:0.85em;color:#666;">'
            'You are receiving this digest because you have email notifications enabled. '
            'To change your preferences, visit the GAPI app.'
            '</p>',
        ])

        body      = '\n'.join(lines)
        html_body = '\n'.join(html_lines)
        return self.send_email(to_address, subject, body, html_body)

    def send_test_email(self, to_address: str) -> bool:
        """Send a test email to verify SMTP configuration.

        Args:
            to_address: Email address to send the test to.

        Returns:
            ``True`` if the test email was delivered, ``False`` otherwise.
        """
        subject = '[GAPI] Email configuration test'
        body    = (
            'This is a test email from GAPI.\n\n'
            'If you received this message, your SMTP configuration is working correctly.\n\n'
            '— The GAPI Team'
        )
        html_body = (
            '<p>This is a test email from <strong>GAPI</strong>.</p>'
            '<p>If you received this message, your SMTP configuration is '
            'working correctly.</p>'
            '<p>— The GAPI Team</p>'
        )
        return self.send_email(to_address, subject, body, html_body)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_message(
        self,
        to_address: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
    ) -> MIMEMultipart:
        """Build an email :class:`~email.mime.multipart.MIMEMultipart` object."""
        if html_body:
            msg = MIMEMultipart('alternative')
        else:
            msg = MIMEMultipart()
        msg['From']    = self._sender
        msg['To']      = to_address
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        if html_body:
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        return msg

    def _send(self, msg: MIMEMultipart, recipients: List[str]) -> None:
        """Establish an SMTP connection and send *msg*."""
        if self._use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(self._host, self._port,
                                  context=context, timeout=self._timeout) as server:
                if self._username:
                    server.login(self._username, self._password)
                server.sendmail(self._sender, recipients, msg.as_string())
        else:
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as server:
                if self._use_tls:
                    server.starttls()
                if self._username:
                    server.login(self._username, self._password)
                server.sendmail(self._sender, recipients, msg.as_string())
