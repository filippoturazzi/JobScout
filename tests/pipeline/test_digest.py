from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlmodel import Session, select

from jobscout.config import Settings
from jobscout.models import Job, Match
from jobscout.models.base import utcnow
from jobscout.pipeline.digest import (
    DIGEST_CAP,
    already_sent_today,
    is_send_window,
    mark_notified,
    select_unnotified,
)
from jobscout.pipeline.users import get_or_create_default_user


def _settings(**kw: int) -> Settings:
    return Settings(_env_file=None, **kw)


def _match(session: Session, user_id: int, score: int | None, **kw: Any) -> Match:
    n = len(session.exec(select(Job)).all())
    job = Job(
        source="t",
        external_id=f"j{n}",
        title="AI Engineer",
        company="Acme",
        remote=True,
        url=f"https://x/{n}",
        description="d",
        content_hash=f"h{n}",
        is_active=kw.pop("is_active", True),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    match = Match(job_id=job.id, user_id=user_id, similarity=0.8, score=score, **kw)
    session.add(match)
    session.commit()
    session.refresh(match)
    return match


def test_selects_only_matches_above_the_threshold(session: Session):
    user = get_or_create_default_user(session)
    high = _match(session, user.id, 80)
    _match(session, user.id, 60)

    rows, held = select_unnotified(session, user.id, min_score=70)

    assert [m.id for m, _ in rows] == [high.id]
    assert held == 0


def test_never_selects_an_already_notified_match(session: Session):
    user = get_or_create_default_user(session)
    _match(session, user.id, 80, notified_at=utcnow())

    rows, _ = select_unnotified(session, user.id, min_score=70)

    assert rows == []


def test_never_selects_a_dismissed_match(session: Session):
    """The user's no survives re-scoring, exactly as it survives staling."""
    user = get_or_create_default_user(session)
    _match(session, user.id, 95, status="dismissed")

    rows, _ = select_unnotified(session, user.id, min_score=70)

    assert rows == []


def test_never_selects_a_match_whose_job_went_inactive(session: Session):
    """Announcing a dead posting is worse than announcing nothing."""
    user = get_or_create_default_user(session)
    _match(session, user.id, 95, is_active=False)

    rows, _ = select_unnotified(session, user.id, min_score=70)

    assert rows == []


def test_never_selects_an_unscored_low_row(session: Session):
    user = get_or_create_default_user(session)
    _match(session, user.id, None, status="low")

    rows, _ = select_unnotified(session, user.id, min_score=70)

    assert rows == []


def test_orders_by_score_descending(session: Session):
    user = get_or_create_default_user(session)
    for score in (72, 95, 83):
        _match(session, user.id, score)

    rows, _ = select_unnotified(session, user.id, min_score=70)

    assert [m.score for m, _ in rows] == [95, 83, 72]


def test_caps_the_batch_and_reports_what_was_held_back(session: Session):
    user = get_or_create_default_user(session)
    for _ in range(DIGEST_CAP + 5):
        _match(session, user.id, 80)

    rows, held = select_unnotified(session, user.id, min_score=70)

    assert (len(rows), held) == (DIGEST_CAP, 5)


def test_mark_notified_touches_only_the_ids_given(session: Session):
    user = get_or_create_default_user(session)
    sent = _match(session, user.id, 80)
    untouched = _match(session, user.id, 80)

    mark_notified(session, [sent.id])

    session.refresh(sent)
    session.refresh(untouched)
    assert sent.notified_at is not None
    assert untouched.notified_at is None


def test_already_sent_today_compares_local_calendar_days(session: Session):
    user = get_or_create_default_user(session)
    tz = ZoneInfo("America/Sao_Paulo")
    now_local = datetime(2026, 10, 1, 9, 0, tzinfo=tz)
    match = _match(session, user.id, 80)
    match.notified_at = now_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    session.add(match)
    session.commit()

    assert already_sent_today(session, user.id, now_local) is True
    assert already_sent_today(session, user.id, now_local + timedelta(days=1)) is False


def test_already_sent_today_survives_a_dst_shift(session: Session):
    """On the spring-forward day the local day is 23 hours long; it is still one day.

    America/New_York springs forward on 2026-03-08 (02:00 -> 03:00). A send at 01:30
    local and a check at 20:00 local sit on opposite sides of the shift.
    """
    user = get_or_create_default_user(session)
    tz = ZoneInfo("America/New_York")
    sent_at_local = datetime(2026, 3, 8, 1, 30, tzinfo=tz)
    match = _match(session, user.id, 80)
    match.notified_at = sent_at_local.astimezone(UTC).replace(tzinfo=None)
    session.add(match)
    session.commit()

    assert already_sent_today(session, user.id, datetime(2026, 3, 8, 20, 0, tzinfo=tz)) is True
    assert already_sent_today(session, user.id, datetime(2026, 3, 9, 0, 30, tzinfo=tz)) is False


def test_already_sent_today_reads_the_stored_utc_in_the_callers_zone(session: Session):
    """22:00 local in UTC+3 is 19:00 UTC, the same date; 01:00 local is 22:00 UTC the day
    before. Comparing the naive value's date directly gets the second case wrong."""
    user = get_or_create_default_user(session)
    tz = ZoneInfo("Europe/Moscow")
    match = _match(session, user.id, 80)
    match.notified_at = datetime(2026, 9, 30, 22, 0)  # naive UTC == 01:00 on Oct 1 in Moscow
    session.add(match)
    session.commit()

    assert already_sent_today(session, user.id, datetime(2026, 10, 1, 12, 0, tzinfo=tz)) is True
    assert already_sent_today(session, user.id, datetime(2026, 9, 30, 12, 0, tzinfo=tz)) is False


def test_already_sent_today_converts_stored_utc_before_comparing_days(session: Session):
    """Stored naive 2026-10-02 01:00 UTC is 21:00 on Oct 1 in New York (UTC-4).

    What this kills, honestly:
    - the raw-`.date()` mutant (compare the naive value's date directly): on every host;
    - the `.replace(tzinfo=UTC)` mutant (let astimezone read the naive value as machine
      local time): only on hosts west of about UTC-3. On a UTC host the two readings
      coincide, so no fixture can separate them.
    CI runs UTC, so the suite cannot catch removal of `.replace`; anyone editing
    already_sent_today must keep that call deliberately.
    """
    user = get_or_create_default_user(session)
    tz = ZoneInfo("America/New_York")
    match = _match(session, user.id, 80)
    match.notified_at = datetime(2026, 10, 2, 1, 0)
    session.add(match)
    session.commit()

    assert already_sent_today(session, user.id, datetime(2026, 10, 1, 23, 0, tzinfo=tz)) is True
    assert already_sent_today(session, user.id, datetime(2026, 10, 2, 9, 0, tzinfo=tz)) is False


def test_already_sent_today_is_false_when_nothing_was_ever_sent(session: Session):
    user = get_or_create_default_user(session)
    _match(session, user.id, 80)

    now = datetime(2026, 10, 1, 9, 0, tzinfo=ZoneInfo("UTC"))
    assert already_sent_today(session, user.id, now) is False


def test_already_sent_today_rejects_a_naive_datetime(session: Session):
    user = get_or_create_default_user(session)

    with pytest.raises(ValueError):
        already_sent_today(session, user.id, datetime(2026, 10, 1, 9, 0))


def test_already_sent_today_ignores_other_users(session: Session):
    user = get_or_create_default_user(session)
    _match(session, user.id, 80, notified_at=datetime(2026, 10, 1, 12, 0))
    now = datetime(2026, 10, 1, 13, 0, tzinfo=ZoneInfo("UTC"))

    assert already_sent_today(session, user.id + 1, now) is False


def test_send_window_opens_at_the_hour_and_stays_open():
    """A window missed because the process was down is still served later the same day."""
    tz = ZoneInfo("America/Sao_Paulo")
    settings = _settings(digest_hour=9)

    assert is_send_window(settings, datetime(2026, 10, 1, 8, 59, tzinfo=tz)) is False
    assert is_send_window(settings, datetime(2026, 10, 1, 9, 0, tzinfo=tz)) is True
    assert is_send_window(settings, datetime(2026, 10, 1, 23, 30, tzinfo=tz)) is True


def test_a_score_equal_to_the_threshold_is_included(session: Session):
    user = get_or_create_default_user(session)
    at = _match(session, user.id, 70)
    _match(session, user.id, 69)

    rows, held = select_unnotified(session, user.id, min_score=70)

    assert [m.id for m, _ in rows] == [at.id]
    assert held == 0


def test_equal_scores_come_back_newest_first(session: Session):
    user = get_or_create_default_user(session)
    first = _match(session, user.id, 80)
    second = _match(session, user.id, 80)
    third = _match(session, user.id, 80)

    rows, _ = select_unnotified(session, user.id, min_score=70)

    assert [m.id for m, _ in rows] == [third.id, second.id, first.id]
