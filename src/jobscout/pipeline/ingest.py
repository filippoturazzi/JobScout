"""Fetch from sources and upsert into the ``job`` table.

Idempotent: re-running with the same data only advances ``last_seen_at``. A changed
title/description updates the text, clears the cached embedding (stage 2 also marks
matches stale) and keeps ``first_seen_at``.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, col, select

from jobscout.models import Job
from jobscout.models.base import utcnow
from jobscout.sources.base import JobSource, RawJob, SearchQuery

log = logging.getLogger(__name__)

_LOOKUP_CHUNK = 500


def content_hash(title: str, description: str) -> str:
    return hashlib.sha256(f"{title}\n{description}".encode()).hexdigest()


@dataclass
class UpsertStats:
    created: int = 0
    updated: int = 0
    changed: int = 0


@dataclass
class IngestResult:
    source: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    changed: int = 0
    error: str | None = None


def upsert_jobs(
    session: Session, raw_jobs: list[RawJob], now: datetime | None = None
) -> UpsertStats:
    now = now or utcnow()
    stats = UpsertStats()
    # Collapse duplicates inside the batch; last one wins.
    by_key = {(r.source, r.external_id): r for r in raw_jobs}
    if not by_key:
        return stats

    existing: dict[tuple[str, str], Job] = {}
    for source_name in {k[0] for k in by_key}:
        ids = [ext_id for (src, ext_id) in by_key if src == source_name]
        for i in range(0, len(ids), _LOOKUP_CHUNK):
            chunk = ids[i : i + _LOOKUP_CHUNK]
            statement = select(Job).where(
                Job.source == source_name, col(Job.external_id).in_(chunk)
            )
            for job in session.exec(statement).all():
                existing[(job.source, job.external_id)] = job

    for key, raw in by_key.items():
        new_hash = content_hash(raw.title, raw.description)
        job = existing.get(key)
        if job is None:
            session.add(
                Job(
                    **raw.model_dump(),
                    content_hash=new_hash,
                    first_seen_at=now,
                    last_seen_at=now,
                    is_active=True,
                )
            )
            stats.created += 1
            continue

        job.last_seen_at = now
        job.is_active = True
        if job.content_hash != new_hash:
            for field, value in raw.model_dump(exclude={"source", "external_id"}).items():
                setattr(job, field, value)
            job.content_hash = new_hash
            job.embedding = None
            stats.changed += 1
        else:
            stats.updated += 1
        session.add(job)

    session.commit()
    return stats


def ingest(
    session: Session,
    sources: list[JobSource],
    query: SearchQuery,
    now: datetime | None = None,
) -> list[IngestResult]:
    """Fetch every source in isolation; one failing source never blocks the others."""
    results: list[IngestResult] = []
    for source in sources:
        result = IngestResult(source=source.name)
        try:
            raw_jobs = source.fetch(query)
            result.fetched = len(raw_jobs)
            stats = upsert_jobs(session, raw_jobs, now=now)
        except Exception as exc:  # noqa: BLE001 - isolate any source failure (fetch or persist)
            session.rollback()
            log.exception("source %s failed", source.name)
            result.error = f"{type(exc).__name__}: {exc}"
            results.append(result)
            continue
        result.created, result.updated, result.changed = (
            stats.created,
            stats.updated,
            stats.changed,
        )
        results.append(result)
    return results
