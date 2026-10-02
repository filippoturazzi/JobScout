"""Notification channels. These depend only on `config` and `models` — never on a
database session, the scheduler, or HTTP."""

from jobscout.config import Settings
from jobscout.notifiers.base import Notifier
from jobscout.notifiers.email import SmtpNotifier

__all__ = ["Notifier", "SmtpNotifier", "build_notifier"]


def build_notifier(settings: Settings, recipient: str) -> Notifier | None:
    """The configured channel, or None when this instance cannot send mail.

    None is a normal state, not an error: an operator who wants no e-mail simply leaves
    SMTP_HOST unset, and the digest job becomes a no-op.
    """
    if not settings.smtp_host or not settings.smtp_from:
        return None
    return SmtpNotifier(settings, recipient)
