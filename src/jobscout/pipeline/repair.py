"""Reprocess stored job text from the payload each row already carries.

A renderer fix — `html_to_text`, the tokenizer — leaves every previously ingested row
holding text produced by the old code. Re-fetching would repair only what is still listed
on the board, costs network, and for paid sources costs quota. `Job.raw` keeps the original
payload, so the repair runs offline over the whole table.

The invariant to preserve is the one `upsert_jobs` maintains: text and `content_hash` move
together, a changed hash clears the embedding derived from it, and the matches scored from
that text go `stale` — except a dismissal, which is the user's own no.
"""

import logging
from dataclasses import dataclass

from sqlmodel import Session, col, select, update

from jobscout.models import Job, Match
from jobscout.pipeline.ingest import content_hash
from jobscout.sources.text import html_to_text

log = logging.getLogger(__name__)

_STALE_CHUNK = 500


@dataclass
class RepairStats:
    repaired: int = 0
    unchanged: int = 0
    skipped: int = 0


def repair_descriptions(session: Session) -> RepairStats:
    """Re-render every job's description from its stored payload. Commits once at the end."""
    stats = RepairStats()
    touched: list[int] = []

    for job in session.exec(select(Job)).all():
        raw_description = (job.raw or {}).get("description")
        if not isinstance(raw_description, str) or not raw_description:
            stats.skipped += 1
            continue

        rendered = html_to_text(raw_description)
        if rendered == job.description:
            stats.unchanged += 1
            continue

        job.description = rendered
        job.content_hash = content_hash(job.title, rendered)
        # The vector described the old text. Keeping it would mean comparing embeddings of
        # different documents, which is worse than having none.
        job.embedding = None
        session.add(job)
        stats.repaired += 1
        if job.id is not None:
            touched.append(job.id)

    for start in range(0, len(touched), _STALE_CHUNK):
        chunk = touched[start : start + _STALE_CHUNK]
        session.exec(
            update(Match)
            .where(col(Match.job_id).in_(chunk), col(Match.status) != "dismissed")
            .values(status="stale")
        )

    session.commit()
    log.info(
        "repaired %d descriptions (%d unchanged, %d without a payload)",
        stats.repaired,
        stats.unchanged,
        stats.skipped,
    )
    return stats
