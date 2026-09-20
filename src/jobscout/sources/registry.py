"""Maps source names (as used in the SOURCES env var) to constructors."""

from collections.abc import Callable

from jobscout.config import Settings
from jobscout.sources.arbeitnow import ArbeitnowSource
from jobscout.sources.base import JobSource

SOURCE_FACTORIES: dict[str, Callable[[Settings], JobSource]] = {
    "arbeitnow": lambda settings: ArbeitnowSource(max_pages=settings.arbeitnow_max_pages),
}


def build_sources(settings: Settings) -> list[JobSource]:
    unknown = [name for name in settings.source_names if name not in SOURCE_FACTORIES]
    if unknown:
        raise ValueError(
            f"Unknown source(s) in SOURCES: {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(SOURCE_FACTORIES))}"
        )
    return [SOURCE_FACTORIES[name](settings) for name in settings.source_names]
