from fastapi import APIRouter

from jobscout.config import get_settings
from jobscout.sources.base import SourceStatus
from jobscout.sources.registry import source_statuses

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[SourceStatus])
def read_sources() -> list[SourceStatus]:
    """Every configured source, and for a dormant one the credential that would wake it."""
    return source_statuses(get_settings())
