from email import message_from_string

import pytest

from jobscout.config import Settings
from jobscout.notifiers import build_notifier
from jobscout.notifiers.email import SmtpNotifier


class _FakeSMTP:
    """Stands in for smtplib.SMTP. Records what would have gone over the wire."""

    instances: list["_FakeSMTP"] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host, self.port = host, port
        self.started_tls = False
        self.logged_in: tuple[str, str] | None = None
        self.sent: str | None = None
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def send_message(self, message: object) -> None:
        self.sent = str(message)


def _settings(**kw: object) -> Settings:
    base: dict[str, object] = {
        "smtp_host": "smtp.test",
        "smtp_port": 2525,
        "smtp_from": "bot@test",
        "smtp_user": "bot@test",
        "smtp_password": "secret",
    }
    base.update(kw)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset() -> None:
    _FakeSMTP.instances.clear()


def test_send_builds_a_message_to_the_recipient(monkeypatch):
    monkeypatch.setattr("jobscout.notifiers.email.smtplib.SMTP", _FakeSMTP)

    SmtpNotifier(_settings(), "me@example.com").send("JobScout: 1 new match", "the body")

    sent = message_from_string(_FakeSMTP.instances[0].sent or "")
    assert sent["To"] == "me@example.com"
    assert sent["From"] == "bot@test"
    assert sent["Subject"] == "JobScout: 1 new match"
    assert "the body" in sent.get_payload()


def test_send_uses_starttls_and_credentials_when_given(monkeypatch):
    monkeypatch.setattr("jobscout.notifiers.email.smtplib.SMTP", _FakeSMTP)

    SmtpNotifier(_settings(), "me@example.com").send("s", "b")

    smtp = _FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.test", 2525)
    assert smtp.started_tls is True
    assert smtp.logged_in == ("bot@test", "secret")


def test_send_skips_login_when_no_credentials(monkeypatch):
    """A local relay often needs neither STARTTLS nor a login."""
    monkeypatch.setattr("jobscout.notifiers.email.smtplib.SMTP", _FakeSMTP)
    settings = _settings(smtp_user=None, smtp_password=None, smtp_starttls=False)

    SmtpNotifier(settings, "me@example.com").send("s", "b")

    smtp = _FakeSMTP.instances[0]
    assert smtp.logged_in is None
    assert smtp.started_tls is False


def test_build_notifier_returns_none_without_a_host():
    assert build_notifier(_settings(smtp_host=None), "me@example.com") is None


def test_build_notifier_returns_none_without_a_sender():
    assert build_notifier(_settings(smtp_from=None), "me@example.com") is None


def test_build_notifier_returns_a_notifier_when_configured():
    assert build_notifier(_settings(), "me@example.com") is not None
