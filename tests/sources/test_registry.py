import pytest

from jobscout.config import Settings
from jobscout.sources.arbeitnow import ArbeitnowSource
from jobscout.sources.registry import SOURCE_FACTORIES, build_sources


def test_default_settings_build_arbeitnow():
    sources = build_sources(Settings(_env_file=None))
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
