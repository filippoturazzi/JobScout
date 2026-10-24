"""Fetch from sources and upsert into the ``job`` table.

Every sighting refreshes metadata and ``last_seen_at``; only a title/description
change clears the cached embedding (stage 2b also marks matches stale) and keeps
``first_seen_at``.

The upsert is keyed on ``(source, external_id)``, with a fingerprint merge in front of it: a
posting whose key is new but whose title + company + city match an existing row from
*another source* is the same vacancy seen twice, so it is recorded under that row's ``raw["duplicates"]``
instead of becoming a second row.
"""

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, col, select, update

from jobscout.models import Job, Match
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


def _normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", folded.lower()).strip()


def fingerprint(title: str, company: str, location: str | None) -> str:
    """Identity of a vacancy across sources: title + company + city.

    Only the first comma-separated component of the location counts, so "São Paulo, SP, BR"
    and "Sao Paulo, Brazil" agree. The city stays in the key on purpose: the same role in
    two cities is two vacancies.
    """
    city = _normalise((location or "").split(",")[0])
    parts = (_normalise(title), _normalise(company), city)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def content_hash(title: str, description: str) -> str:
    return hashlib.sha256(f"{title}\n{description}".encode()).hexdigest()


@dataclass
class UpsertStats:
    created: int = 0
    updated: int = 0
    changed: int = 0
    merged: int = 0
    created_ids: list[int] = field(default_factory=list)
    changed_ids: list[int] = field(default_factory=list)


@dataclass
class IngestResult:
    source: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    changed: int = 0
    merged: int = 0
    created_ids: list[int] = field(default_factory=list)
    changed_ids: list[int] = field(default_factory=list)
    error: str | None = None


def _mark_matches_stale(session: Session, job_ids: list[int]) -> None:
    """A changed description invalidates every score derived from it — except a user's own no."""
    for start in range(0, len(job_ids), _LOOKUP_CHUNK):
        chunk = job_ids[start : start + _LOOKUP_CHUNK]
        session.exec(
            update(Match)
            .where(col(Match.job_id).in_(chunk), col(Match.status) != "dismissed")
            .values(status="stale")
        )


def _load_by_fingerprint(session: Session, fingerprints: set[str]) -> dict[str, Job]:
    """Existing rows for these fingerprints; the oldest wins. NULL fingerprints never match."""
    found: dict[str, Job] = {}
    wanted = sorted(fingerprints)
    for start in range(0, len(wanted), _LOOKUP_CHUNK):
        chunk = wanted[start : start + _LOOKUP_CHUNK]
        statement = select(Job).where(col(Job.fingerprint).in_(chunk)).order_by(col(Job.id).desc())
        for job in session.exec(statement).all():
            if job.fingerprint is not None:
                found[job.fingerprint] = job  # descending ids: the lowest id is written last
    return found


def _record_duplicate(job: Job, raw: RawJob) -> None:
    """Note ``raw`` as another sighting of ``job`` without touching the first source's payload."""
    entry = {"source": raw.source, "external_id": raw.external_id, "url": raw.url}
    duplicates = [dict(d) for d in job.raw.get("duplicates", [])]
    for i, known in enumerate(duplicates):
        if (known["source"], known["external_id"]) == (raw.source, raw.external_id):
            duplicates[i] = entry
            break
    else:
        duplicates.append(entry)
    # A new dict: mutating the JSON column in place would not mark it dirty.
    job.raw = {**job.raw, "duplicates": duplicates}


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
            for found_job in session.exec(statement).all():
                existing[(found_job.source, found_job.external_id)] = found_job

    # Vacancies already stored (or created earlier in this batch), by fingerprint.
    by_fingerprint = _load_by_fingerprint(
        session,
        {
            fingerprint(r.title, r.company, r.location)
            for k, r in by_key.items()
            if k not in existing
        },
    )

    created_jobs: list[Job] = []
    changed_jobs: list[Job] = []
    for key, raw in by_key.items():
        new_hash = content_hash(raw.title, raw.description)
        job = existing.get(key)
        if job is None:
            new_fingerprint = fingerprint(raw.title, raw.company, raw.location)
            twin = by_fingerprint.get(new_fingerprint)
            # Cross-source only: a same-source twin is a distinct opening or a relisting, and
            # collapsing it could silently lose a real vacancy.
            if twin is not None and twin.source != raw.source:
                twin.last_seen_at = now
                twin.is_active = True
                _record_duplicate(twin, raw)
                session.add(twin)
                stats.merged += 1
                continue
            job = Job(
                **raw.model_dump(),
                content_hash=new_hash,
                fingerprint=new_fingerprint,
                first_seen_at=now,
                last_seen_at=now,
                is_active=True,
            )
            session.add(job)
            by_fingerprint[new_fingerprint] = job
            created_jobs.append(job)
            stats.created += 1
            continue

        # Every sighting: liveness + metadata refresh.
        job.last_seen_at = now
        job.is_active = True
        duplicates = job.raw.get("duplicates")
        for name in _METADATA_FIELDS:
            setattr(job, name, getattr(raw, name))
        if duplicates:  # the other sources' record belongs to the row, not to this source
            job.raw = {**job.raw, "duplicates": duplicates}
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
        # Back-fills rows that predate the column, and follows a title/company/city change.
        job.fingerprint = fingerprint(job.title, job.company, job.location)
        session.add(job)

    session.flush()  # assigns ids for the new rows
    stats.created_ids = [job.id for job in created_jobs if job.id is not None]
    stats.changed_ids = [job.id for job in changed_jobs if job.id is not None]
    _mark_matches_stale(session, stats.changed_ids)
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
        result.created, result.updated, result.changed, result.merged = (
            stats.created,
            stats.updated,
            stats.changed,
            stats.merged,
        )
        result.created_ids, result.changed_ids = stats.created_ids, stats.changed_ids
        results.append(result)
    return results
