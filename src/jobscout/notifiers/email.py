"""SMTP delivery. Stdlib only — `smtplib` and `email.message` need no dependency."""

import smtplib
import ssl
from email.message import EmailMessage

from jobscout.config import Settings


class SmtpNotifier:
    """Sends one message per call over a fresh SMTP connection.

    A fresh connection per digest is the right trade here: the job runs at most once a
    day per user, so pooling would add state for no benefit.

    STARTTLS uses a verifying context (certificate and hostname are checked), because
    the password is sent right after the handshake. Consequence: a relay presenting a
    self-signed or mismatched certificate fails to connect with an SSL error instead of
    silently downgrading. That visible error is intended; fix the relay's certificate,
    or set SMTP_STARTTLS=false for a trusted local relay.
    """

    def __init__(self, settings: Settings, recipient: str) -> None:
        self._settings = settings
        self._recipient = recipient

    def send(self, subject: str, body: str) -> None:
        settings = self._settings
        assert settings.smtp_host is not None, "build_notifier guarantees a host"
        assert settings.smtp_from is not None, "build_notifier guarantees a sender"

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.smtp_from
        message["To"] = self._recipient
        message.set_content(body)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user and settings.smtp_password:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
