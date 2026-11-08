"""One-time conversion of a database from before saved searches into the current shape.

Preferences used to be one row per user, and matches were keyed by (job, user). Now both hang
off a `Search`. The upgrade turns each user's preferences into that user's first search and
moves the matches under it, keeping their ids and statuses: an applied or dismissed verdict
must survive. SQLite only: no released install ran on Postgres.
"""

import logging
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, MetaData, Table, insert, inspect, make_url, update
from sqlmodel import SQLModel

from jobscout.db import needs_upgrade
from jobscout.models import Match, Search, SearchJob, UserPreferences
from jobscout.pipeline.conversation import from_preferences, title

log = logging.getLogger(__name__)

UNTITLED = "My search"


@dataclass(frozen=True)
class UpgradeReport:
    searches: int
    matches: int
    runs: int


def backup_sqlite(url: str, now: datetime) -> Path | None:
    """Copy a SQLite file to `<file>.bak-YYYYMMDD-HHMMSS`; None for in-memory or other URLs."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or parsed.database in (None, "", ":memory:"):
        return None
    source = Path(parsed.database)
    target = source.with_name(f"{source.name}.bak-{now:%Y%m%d-%H%M%S}")
    shutil.copy2(source, target)
    return target


@contextmanager
def _transaction(engine: Engine) -> Iterator[Connection]:
    """One transaction that covers DDL too.

    pysqlite opens a transaction only before INSERT/UPDATE/DELETE, so under `engine.begin()`
    a DROP TABLE issued before the first insert commits on its own and survives a rollback.
    On SQLite the driver is put in autocommit and the transaction is opened by hand.
    """
    if engine.dialect.name != "sqlite":
        with engine.begin() as connection:
            yield connection
        return
    with engine.connect() as connection:
        connection.execution_options(isolation_level="AUTOCOMMIT")
        connection.exec_driver_sql("BEGIN")
        try:
            yield connection
        except BaseException:
            connection.exec_driver_sql("ROLLBACK")
            raise
        connection.exec_driver_sql("COMMIT")


def _rows(connection: Connection, name: str) -> tuple[Table, list[dict[str, Any]]]:
    """The old table, reflected, and its rows (JSON columns come back decoded)."""
    table = Table(name, MetaData(), autoload_with=connection)
    rows = [dict(row._mapping) for row in connection.execute(table.select().order_by(table.c.id))]
    return table, rows


def _fields(row: dict[str, Any], model: type[SQLModel]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key in model.model_fields}


def _add_run_search_id(connection: Connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("run")}
    if "search_id" in columns:
        return
    connection.exec_driver_sql("ALTER TABLE run ADD COLUMN search_id INTEGER")
    run = SQLModel.metadata.tables["run"]
    for index in run.indexes:
        if [column.name for column in index.columns] == ["search_id"]:
            index.create(connection)


def upgrade_database(engine: Engine) -> UpgradeReport:
    """Rebuild a pre-searches database in place, in one transaction; a no-op when current."""
    if not needs_upgrade(engine):
        return UpgradeReport(searches=0, matches=0, runs=0)
    tables = SQLModel.metadata.tables
    searches = matches = runs = 0
    with _transaction(engine) as connection:
        old_prefs_table, old_prefs = _rows(connection, "user_preferences")
        old_match_table, old_matches = _rows(connection, "match")
        old_match_table.drop(connection)
        old_prefs_table.drop(connection)
        SQLModel.metadata.create_all(connection)
        _add_run_search_id(connection)

        prefs_by_user = {row["user_id"]: row for row in old_prefs}
        # A user with matches but no preferences still gets a search, so no match is lost.
        user_ids = sorted(prefs_by_user.keys() | {row["user_id"] for row in old_matches})
        for user_id in user_ids:
            prefs = UserPreferences(**_fields(prefs_by_user.get(user_id, {}), UserPreferences))
            prefs.user_id = user_id
            conversation = from_preferences(prefs)
            search = Search(
                user_id=user_id,
                title=title(conversation)
                if conversation.reading is not None and conversation.reading.terms
                else UNTITLED,
                conversation=conversation.model_dump(mode="json"),
            )
            result = connection.execute(
                insert(tables["search"]).values(search.model_dump(exclude={"id"}))
            )
            assert result.inserted_primary_key is not None, "an insert reports its key"
            search_id = result.inserted_primary_key[0]
            searches += 1
            prefs.search_id = search_id
            connection.execute(insert(tables["user_preferences"]).values(prefs.model_dump()))

            user_matches = [row for row in old_matches if row["user_id"] == user_id]
            for row in user_matches:
                match = Match(**_fields(row, Match))
                match.search_id = search_id
                connection.execute(insert(tables["match"]).values(match.model_dump()))
                matches += 1
            for job_id in sorted({row["job_id"] for row in user_matches}):
                fetched = SearchJob(search_id=search_id, job_id=job_id)
                connection.execute(insert(tables["search_job"]).values(fetched.model_dump()))

            run = tables["run"]
            linked = connection.execute(
                update(run)
                .where(run.c.user_id == user_id, run.c.job == "search")
                .values(search_id=search_id)
            )
            runs += linked.rowcount
    log.info("upgraded the database: searches=%d matches=%d runs=%d", searches, matches, runs)
    return UpgradeReport(searches=searches, matches=matches, runs=runs)
