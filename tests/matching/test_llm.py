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


def test_google_without_key_explains_what_to_set():
    with pytest.raises(MissingProviderError) as excinfo:
        chat_model(_settings(llm_provider="google", google_api_key=None))
    assert "GOOGLE_API_KEY" in str(excinfo.value)
    assert ".env" in str(excinfo.value)


def test_key_from_dotenv_is_accepted(tmp_path, monkeypatch):
    """A key present only in .env must satisfy the check — the documented onboarding path."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GOOGLE_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    settings = Settings()  # no _env_file=None: we want .env to be read
    assert settings.google_api_key == "from-dotenv"
    assert chat_model(settings) is not None  # constructs without raising


def test_ollama_needs_no_key():
    import jobscout.matching.llm as llm

    monkey = llm.PROVIDERS["ollama"]
    assert monkey.key_setting == ""


def test_missing_package_explains_the_install(monkeypatch):
    import jobscout.matching.llm as llm

    def _boom(name: str) -> None:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(llm, "_import_module", _boom)
    with pytest.raises(MissingProviderError, match="pip install langchain-openai"):
        chat_model(_settings(llm_provider="openai", openai_api_key="x"))
