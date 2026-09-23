import pytest

from jobscout.config import Settings
from jobscout.matching.llm import MissingProviderError, chat_model, embeddings


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_unknown_provider_names_the_available_ones():
    with pytest.raises(MissingProviderError, match="nope"):
        chat_model(_settings(llm_provider="nope"))
    with pytest.raises(MissingProviderError, match="google"):
        embeddings(_settings(llm_provider="nope"))


def test_google_without_key_explains_what_to_set(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(MissingProviderError) as excinfo:
        chat_model(_settings(llm_provider="google"))
    assert "GOOGLE_API_KEY" in str(excinfo.value)


def test_missing_package_explains_the_install(monkeypatch):
    import jobscout.matching.llm as llm

    def _boom(name: str) -> None:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(llm, "_import_module", _boom)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    with pytest.raises(MissingProviderError, match="pip install langchain-openai"):
        chat_model(_settings(llm_provider="openai"))
