"""Choosing what goes into a digest, and recording that it went.

`notified_at` is the only thing that decides whether a match has been announced. It is
deliberately independent of `status`, which staling rewrites.
"""

from datetime import UTC, datetime

from sqlmodel import Session, col, desc, func, select

from jobscout.config import Settings
from jobscout.models import CLOSED_STATUSES, Job, Match
from jobscout.models.base import utcnow

DIGEST_CAP = 20
"""Most rows in one message. The first digest after a preference change can qualify
hundreds; an unreadable e-mail is worse than a second one tomorrow."""


def select_unnotified(
    session: Session, user_id: int, min_score: int, limit: int = DIGEST_CAP
) -> tuple[list[tuple[Match, Job]], int]:
    """The rows to announce, best first, and how many qualifying rows did not fit."""
    statement = (
        select(Match, Job)
        .join(Job, col(Match.job_id) == col(Job.id))
        .where(
            col(Match.user_id) == user_id,
            col(Match.notified_at).is_(None),
            col(Match.status).not_in(CLOSED_STATUSES),
            col(Match.score).is_not(None),
            col(Match.score) >= min_score,
            col(Job.is_active).is_(True),
        )
        .order_by(desc(col(Match.score)), desc(col(Match.id)))
    )
    qualifying = list(session.exec(statement).all())
    return qualifying[:limit], max(0, len(qualifying) - limit)


def mark_notified(session: Session, match_ids: list[int], now: datetime | None = None) -> None:
    """Record the announcement. Called only after the channel accepted the message."""
    if not match_ids:
        return
    stamp = now or utcnow()
    for match in session.exec(select(Match).where(col(Match.id).in_(match_ids))).all():
        match.notified_at = stamp
        session.add(match)
    session.commit()


def already_sent_today(session: Session, user_id: int, now_local: datetime) -> bool:
    """Has this user had a digest today, in the server's local calendar?

    `notified_at` is stored naive UTC, so it is converted before the day is compared —
    otherwise a send at 22:00 local would look like tomorrow to a UTC+3 server.
    """
    if now_local.tzinfo is None:
        raise ValueError("now_local must be timezone-aware")
    latest = session.exec(
        select(func.max(col(Match.notified_at))).where(col(Match.user_id) == user_id)
    ).one()
    if latest is None:
        return False
    # Keep .replace(tzinfo=UTC): without it astimezone reads the naive value as machine-local
    # time. Tests cannot catch its removal on a UTC host (CI), so keep it deliberately.
    local = latest.replace(tzinfo=UTC).astimezone(now_local.tzinfo)
    return local.date() == now_local.date()


def is_send_window(settings: Settings, now_local: datetime) -> bool:
    """At or after DIGEST_HOUR. Deliberately not an exact-hour match: a window missed
    because the process was down is still served later the same day."""
    return now_local.hour >= settings.digest_hour
