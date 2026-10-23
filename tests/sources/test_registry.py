import pytest

from jobscout.config import Settings
from jobscout.sources.arbeitnow import ArbeitnowSource
from jobscout.sources.registry import (
    SOURCE_FACTORIES,
    SOURCE_MISSING_CREDENTIALS,
    build_sources,
    source_statuses,
)


def test_arbeitnow_builds_when_listed():
    sources = build_sources(Settings(_env_file=None, sources="arbeitnow"))
    assert len(sources) == 1
    assert isinstance(sources[0], ArbeitnowSource)
    assert sources[0].name == "arbeitnow"


def test_unknown_source_raises():
    with pytest.raises(ValueError, match="nope"):
        build_sources(Settings(_env_file=None, sources="arbeitnow,nope"))


def test_every_factory_name_matches_source_name():
    settings = Settings(_env_file=None)
    for name, factory in SOURCE_FACTORIES.items():
        assert factory(settings).name == name


class _FakeKeyedSource:
    name = "keyed"
    supports_search = True

    def fetch(self, query):
        return []


@pytest.fixture
def keyed_source(monkeypatch):
    """Register a source that needs KEYED_API_KEY, restored by monkeypatch afterwards."""
    monkeypatch.setitem(SOURCE_FACTORIES, "keyed", lambda settings: _FakeKeyedSource())
    monkeypatch.setitem(SOURCE_MISSING_CREDENTIALS, "keyed", lambda settings: ["KEYED_API_KEY"])


def test_a_source_without_its_credentials_is_not_built(keyed_source):
    settings = Settings(_env_file=None, sources="arbeitnow,keyed")
    assert [s.name for s in build_sources(settings)] == ["arbeitnow"]


def test_source_statuses_name_the_missing_credential(keyed_source):
    settings = Settings(_env_file=None, sources="arbeitnow,keyed")
    statuses = {s.name: s for s in source_statuses(settings)}
    assert statuses["arbeitnow"].active is True
    assert statuses["keyed"].active is False
    assert statuses["keyed"].reason is not None
    assert "KEYED_API_KEY" in statuses["keyed"].reason


def test_an_unknown_source_name_still_raises():
    with pytest.raises(ValueError, match="Unknown source"):
        build_sources(Settings(_env_file=None, sources="nope"))


def test_arbeitnow_is_not_enabled_by_default():
    assert "arbeitnow" not in Settings(_env_file=None).source_names


def test_the_scheduler_is_off_by_default(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)  # conftest sets it for the suite
    assert Settings(_env_file=None).scheduler_enabled is False


def test_arbeitnow_does_not_support_search():
    assert ArbeitnowSource().supports_search is False
