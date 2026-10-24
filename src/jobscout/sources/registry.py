"""Maps source names (as used in the SOURCES env var) to constructors."""

from collections.abc import Callable

from jobscout.config import Settings
from jobscout.sources.arbeitnow import ArbeitnowSource
from jobscout.sources.base import JobSource, SourceStatus
from jobscout.sources.himalayas import HimalayasSource
from jobscout.sources.indeed import IndeedSource
from jobscout.sources.linkedin import LinkedInSource
from jobscout.sources.remotive import RemotiveSource

SOURCE_FACTORIES: dict[str, Callable[[Settings], JobSource]] = {
    "arbeitnow": lambda settings: ArbeitnowSource(max_pages=settings.arbeitnow_max_pages),
    "himalayas": lambda settings: HimalayasSource(),
    "remotive": lambda settings: RemotiveSource(),
    "linkedin": lambda settings: LinkedInSource(settings),
    "indeed": lambda settings: IndeedSource(settings),
}

# Companion to SOURCE_FACTORIES: for sources that need credentials, returns the names of
# the environment variables that are missing. A source absent from this map needs none.
SOURCE_MISSING_CREDENTIALS: dict[str, Callable[[Settings], list[str]]] = {}


def _missing_credentials(name: str, settings: Settings) -> list[str]:
    predicate = SOURCE_MISSING_CREDENTIALS.get(name)
    return predicate(settings) if predicate is not None else []


def _check_known(settings: Settings) -> None:
    unknown = [name for name in settings.source_names if name not in SOURCE_FACTORIES]
    if unknown:
        raise ValueError(
            f"Unknown source(s) in SOURCES: {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(SOURCE_FACTORIES))}"
        )


def build_sources(settings: Settings) -> list[JobSource]:
    """Build the configured sources. A typo in SOURCES raises; a known source whose
    credentials are absent is skipped (see ``source_statuses`` for why)."""
    _check_known(settings)
    return [
        SOURCE_FACTORIES[name](settings)
        for name in settings.source_names
        if not _missing_credentials(name, settings)
    ]


def source_statuses(settings: Settings) -> list[SourceStatus]:
    _check_known(settings)
    statuses: list[SourceStatus] = []
    for name in settings.source_names:
        missing = _missing_credentials(name, settings)
        if missing:
            reason = f"missing {', '.join(missing)}"
            statuses.append(SourceStatus(name=name, active=False, reason=reason))
        else:
            statuses.append(SourceStatus(name=name, active=True))
    return statuses
