"""Fetch from sources and upsert into the ``job`` table.

Every sighting refreshes metadata and ``last_seen_at``; only a title/description
change clears the cached embedding (stage 2b also marks matches stale) and keeps
``first_seen_at``.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, col, select

from jobscout.models import Job
from jobscout.models.base import utcnow
from jobscout.sources.base import JobSource, RawJob, SearchQuery

log = logging.getLogger(__name__)

_LOOKUP_CHUNK = 500

_METADATA_FIELDS = (
    "company",
    "location",
    "remote",
    "url",
    "salary_min",
    "salary_max",
    "salary_currency",
    "tags",
    "posted_at",
    "raw",
)


def content_hash(title: str, description: str) -> str:
    return hashlib.sha256(f"{title}\n{description}".encode()).hexdigest()


@dataclass
class UpsertStats:
    created: int = 0
    updated: int = 0
    changed: int = 0
    created_ids: list[int] = field(default_factory=list)
    changed_ids: list[int] = field(default_factory=list)


@dataclass
class IngestResult:
    source: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    changed: int = 0
    created_ids: list[int] = field(default_factory=list)
    changed_ids: list[int] = field(default_factory=list)
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

    created_jobs: list[Job] = []
    changed_jobs: list[Job] = []
    for key, raw in by_key.items():
        new_hash = content_hash(raw.title, raw.description)
        job = existing.get(key)
        if job is None:
            job = Job(
                **raw.model_dump(),
                content_hash=new_hash,
                first_seen_at=now,
                last_seen_at=now,
                is_active=True,
            )
            session.add(job)
            created_jobs.append(job)
            stats.created += 1
            continue

        # Every sighting: liveness + metadata refresh.
        job.last_seen_at = now
        job.is_active = True
        for name in _METADATA_FIELDS:
            setattr(job, name, getattr(raw, name))
        # Only a text change invalidates what was derived from the text.
        if job.content_hash != new_hash:
            job.title = raw.title
            job.description = raw.description
            job.content_hash = new_hash
            job.embedding = None
            changed_jobs.append(job)
            stats.changed += 1
        else:
            stats.updated += 1
        session.add(job)

    session.flush()  # assigns ids for the new rows
    stats.created_ids = [job.id for job in created_jobs if job.id is not None]
    stats.changed_ids = [job.id for job in changed_jobs if job.id is not None]
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
            log.error(
                "source %s failed: %s: %s",
                source.name,
                type(exc).__name__,
                exc,
                exc_info=log.isEnabledFor(logging.DEBUG),
            )
            result.error = f"{type(exc).__name__}: {exc}"
            results.append(result)
            continue
        result.created, result.updated, result.changed = (
            stats.created,
            stats.updated,
            stats.changed,
        )
        result.created_ids, result.changed_ids = stats.created_ids, stats.changed_ids
        results.append(result)
    return results
