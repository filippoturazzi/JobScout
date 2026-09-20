"""Shared model helpers.

All timestamps are naive UTC. SQLite discards tzinfo on read, so storing aware datetimes
would make comparisons between fresh and loaded values fail. Use ``utcnow()`` everywhere.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
