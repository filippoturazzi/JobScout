import types
from typing import Any

import pytest

from jobscout.config import Settings
from jobscout.matching.llm import (
    MissingProviderError,
    chat_model,
    chat_model_name,
    detect_provider,
    embedding_key_found,
    embeddings,
    provider_key_found,
    resolve_chat,
    resolve_embeddings,
)

GROQ = "gsk_" + "a" * 52
ANTHROPIC = "sk-ant-api03-" + "b" * 40
GOOGLE = "AIza" + "c" * 35
OPENAI = "sk-proj-" + "d" * 40
DEEPSEEK = "sk-" + "0123456789abcdef" * 2


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _recorder(monkeypatch, class_name: str) -> dict[str, Any]:
    """Stub every provider module with one class that records its constructor kwargs."""
    import jobscout.matching.llm as llm

    recorded: dict[str, Any] = {}

    class _Recorder:
        def __init__(self, **kwargs: Any) -> None:
            recorded.update(kwargs)

    stub = types.ModuleType("stub")
    setattr(stub, class_name, _Recorder)
    monkeypatch.setattr(llm, "_import_module", lambda _name: stub)
    return recorded


@pytest.mark.parametrize(
    ("key", "provider"),
    [
        (GROQ, "groq"),
        (ANTHROPIC, "anthropic"),
        (GOOGLE, "google"),
        (OPENAI, "openai"),
        ("sk-svcacct-" + "e" * 40, "openai"),
        (DEEPSEEK, "deepseek"),
        ("  " + GROQ + "  ", "groq"),
        ("sk-" + "Z" * 48, None),  # a legacy OpenAI key: not sure enough to say
        ("whatever", None),
    ],
)
def test_detect_provider_from_the_key(key, provider):
    assert detect_provider(key) == provider


def test_one_key_is_enough_to_pick_the_provider_and_its_default_model():
    choice = resolve_chat(_settings(llm_api_key=GROQ))
    assert (choice.provider, choice.key) == ("groq", GROQ)
    assert choice.model == "openai/gpt-oss-120b"


def test_llm_model_overrides_the_default_model():
    choice = resolve_chat(_settings(llm_api_key=DEEPSEEK, llm_model="deepseek-v4-pro"))
    assert (choice.provider, choice.model) == ("deepseek", "deepseek-v4-pro")


def test_explicit_provider_wins_over_an_unrecognised_key():
    choice = resolve_chat(_settings(llm_api_key="custom-key", llm_provider="Groq"))
    assert choice.provider == "groq"


def test_a_generic_sk_key_falls_back_to_openai():
    assert resolve_chat(_settings(llm_api_key="sk-" + "Z" * 48)).provider == "openai"


def test_an_unrecognisable_key_asks_for_llm_provider():
    with pytest.raises(MissingProviderError, match="LLM_PROVIDER"):
        resolve_chat(_settings(llm_api_key="whatever"))


def test_a_provider_that_contradicts_the_key_is_reported():
    """The upgrade trap: LLM_PROVIDER=google left in .env next to a Groq key."""
    with pytest.raises(MissingProviderError) as excinfo:
        resolve_chat(_settings(llm_api_key=GROQ, llm_provider="google"))
    assert "groq" in str(excinfo.value) and "google" in str(excinfo.value)


def test_legacy_provider_keys_still_work():
    choice = resolve_chat(_settings(google_api_key=GOOGLE))
    assert (choice.provider, choice.key, choice.model) == ("google", GOOGLE, "gemini-3.5-flash")
    assert resolve_chat(_settings(openai_api_key=OPENAI)).provider == "openai"
    assert resolve_chat(_settings(llm_provider="openai", openai_api_key=OPENAI)).key == OPENAI


def test_no_key_at_all_names_llm_api_key():
    with pytest.raises(MissingProviderError) as excinfo:
        chat_model(_settings())
    assert "LLM_API_KEY" in str(excinfo.value)
    assert ".env" in str(excinfo.value)


def test_a_provider_without_its_key_names_llm_api_key():
    with pytest.raises(MissingProviderError, match="LLM_API_KEY"):
        chat_model(_settings(llm_provider="anthropic"))


def test_unknown_provider_names_the_available_ones():
    with pytest.raises(MissingProviderError) as excinfo:
        chat_model(_settings(llm_provider="nope", llm_api_key="x"))
    assert "nope" in str(excinfo.value) and "groq" in str(excinfo.value)
    with pytest.raises(MissingProviderError, match="google"):
        embeddings(_settings(embedding_provider="nope"))


def test_ollama_needs_no_key():
    assert resolve_chat(_settings(llm_provider="ollama")).key is None
    assert provider_key_found(_settings(llm_provider="ollama")) is True


def test_key_from_dotenv_is_accepted(tmp_path, monkeypatch):
    """A key present only in .env must satisfy the check — the documented onboarding path."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"LLM_API_KEY={GROQ}\n", encoding="utf-8")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    settings = Settings()  # no _env_file=None: we want .env to be read
    assert settings.llm_api_key == GROQ
    assert chat_model(settings) is not None  # constructs without raising


def test_missing_package_explains_the_install(monkeypatch):
    import jobscout.matching.llm as llm

    def _boom(name: str) -> None:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(llm, "_import_module", _boom)
    with pytest.raises(MissingProviderError, match="pip install langchain-groq"):
        chat_model(_settings(llm_api_key=GROQ))


def test_chat_model_receives_key_model_and_temperature(monkeypatch):
    recorded = _recorder(monkeypatch, "ChatGroq")
    chat_model(_settings(llm_api_key=GROQ))
    assert recorded == {"model": "openai/gpt-oss-120b", "temperature": 0, "api_key": GROQ}


def test_embeddings_default_to_gemini_with_their_own_key(monkeypatch):
    """Chat on Groq, embeddings on Gemini's free tier: the two-key setup."""
    recorded = _recorder(monkeypatch, "GoogleGenerativeAIEmbeddings")
    embeddings(_settings(llm_api_key=GROQ, google_api_key=GOOGLE, embedding_dim=768))
    assert recorded == {
        "model": "gemini-embedding-2",
        "api_key": GOOGLE,
        "output_dimensionality": 768,
    }


def test_a_google_llm_key_also_serves_the_embeddings():
    choice = resolve_embeddings(_settings(llm_api_key=GOOGLE))
    assert (choice.provider, choice.key) == ("google", GOOGLE)


def test_a_non_google_llm_key_never_reaches_gemini_embeddings():
    with pytest.raises(MissingProviderError) as excinfo:
        embeddings(_settings(llm_api_key=GROQ))
    message = str(excinfo.value)
    assert "GOOGLE_API_KEY" in message and "EMBEDDING_PROVIDER" in message


def test_openai_embeddings_use_their_default_model():
    choice = resolve_embeddings(_settings(embedding_provider="openai", llm_api_key=OPENAI))
    assert (choice.model, choice.key) == ("text-embedding-3-small", OPENAI)


def test_providers_without_embeddings_are_refused():
    with pytest.raises(MissingProviderError, match="google"):
        resolve_embeddings(_settings(embedding_provider="groq", llm_api_key=GROQ))


def test_provider_key_found():
    assert provider_key_found(_settings()) is False
    assert provider_key_found(_settings(llm_api_key=GROQ)) is True
    assert provider_key_found(_settings(llm_api_key=GROQ, llm_provider="google")) is False
    assert provider_key_found(_settings(llm_provider="google", google_api_key=GOOGLE)) is True
    assert provider_key_found(_settings(llm_provider="nope")) is False


def test_embedding_key_found():
    assert embedding_key_found(_settings(llm_api_key=GROQ)) is False
    assert embedding_key_found(_settings(llm_api_key=GROQ, google_api_key=GOOGLE)) is True
    assert embedding_key_found(_settings(llm_api_key=GOOGLE)) is True
    assert embedding_key_found(_settings(embedding_provider="ollama")) is True


def test_chat_model_name_never_raises():
    assert chat_model_name(_settings(llm_api_key=GROQ)) == "openai/gpt-oss-120b"
    assert chat_model_name(_settings(llm_model="my-model")) == "my-model"
    assert chat_model_name(_settings()) == ""
