"""Chat model and embeddings, chosen from operator config.

The chat model needs one key, ``LLM_API_KEY``, whichever provider issued it: the provider is
read from the key's prefix unless ``LLM_PROVIDER`` names it, and ``LLM_MODEL`` defaults to a
cheap model of that provider. Embeddings are separate (``EMBEDDING_PROVIDER``, Gemini by
default) because most chat providers offer none.

Providers are imported lazily so the tests run without touching any of them. Keys are read
from ``Settings`` (which loads them from ``.env`` or the real environment) and passed to the
provider classes explicitly, rather than relying on the provider packages' own lookups.
"""

import importlib
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from jobscout.config import Settings

logger = logging.getLogger(__name__)


class MissingProviderError(RuntimeError):
    """The configured provider is unknown, not installed, or missing its API key."""


@dataclass(frozen=True)
class _ChatProvider:
    module: str
    package: str
    chat_class: str
    default_model: str
    needs_key: bool = True
    # Settings attribute of a provider-specific key accepted when LLM_API_KEY is empty.
    legacy_key: str = ""


@dataclass(frozen=True)
class _EmbeddingProvider:
    module: str
    package: str
    embeddings_class: str
    default_model: str
    key_setting: str = ""  # Settings attribute; "" when the provider needs no key
    key_env: str = ""
    supports_output_dimensionality: bool = False


# Default models are the cheap tier of each provider (checked 2026-11): a job evaluation is a
# short structured answer, so the small models are enough and keep a run within free quotas.
CHAT_PROVIDERS: dict[str, _ChatProvider] = {
    "google": _ChatProvider(
        module="langchain_google_genai",
        package="langchain-google-genai",
        chat_class="ChatGoogleGenerativeAI",
        default_model="gemini-3.5-flash",
        legacy_key="google_api_key",
    ),
    "openai": _ChatProvider(
        module="langchain_openai",
        package="langchain-openai",
        chat_class="ChatOpenAI",
        default_model="gpt-5-mini",
        legacy_key="openai_api_key",
    ),
    "anthropic": _ChatProvider(
        module="langchain_anthropic",
        package="langchain-anthropic",
        chat_class="ChatAnthropic",
        default_model="claude-haiku-5-5",
    ),
    "groq": _ChatProvider(
        module="langchain_groq",
        package="langchain-groq",
        chat_class="ChatGroq",
        default_model="openai/gpt-oss-120b",
    ),
    "deepseek": _ChatProvider(
        module="langchain_deepseek",
        package="langchain-deepseek",
        chat_class="ChatDeepSeek",
        default_model="deepseek-flash",
    ),
    "ollama": _ChatProvider(
        module="langchain_ollama",
        package="langchain-ollama",
        chat_class="ChatOllama",
        default_model="llama3.1",
        needs_key=False,  # local server
    ),
}

EMBEDDING_PROVIDERS: dict[str, _EmbeddingProvider] = {
    "google": _EmbeddingProvider(
        module="langchain_google_genai",
        package="langchain-google-genai",
        embeddings_class="GoogleGenerativeAIEmbeddings",
        default_model="gemini-embedding-2",
        key_setting="google_api_key",
        key_env="GOOGLE_API_KEY",
        supports_output_dimensionality=True,
    ),
    "openai": _EmbeddingProvider(
        module="langchain_openai",
        package="langchain-openai",
        embeddings_class="OpenAIEmbeddings",
        default_model="text-embedding-3-small",
        key_setting="openai_api_key",
        key_env="OPENAI_API_KEY",
    ),
    "ollama": _EmbeddingProvider(
        module="langchain_ollama",
        package="langchain-ollama",
        embeddings_class="OllamaEmbeddings",
        default_model="nomic-embed-text",
    ),
}

# Prefixes distinctive enough to name the provider. A bare `sk-` is not: legacy OpenAI keys
# look like that too, which is why DeepSeek is matched by its exact shape and the rest of
# `sk-` is only a fallback (see `_chat_provider_name`).
_KEY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"gsk_"), "groq"),
    (re.compile(r"sk-ant-"), "anthropic"),
    (re.compile(r"AIza"), "google"),
    (re.compile(r"sk-(proj|svcacct|admin)-"), "openai"),
    (re.compile(r"sk-[0-9a-f]{32}$"), "deepseek"),
]


@dataclass(frozen=True)
class ChatChoice:
    provider: str
    model: str
    key: str | None


@dataclass(frozen=True)
class EmbeddingChoice:
    provider: str
    model: str
    key: str | None


def detect_provider(key: str) -> str | None:
    """The provider that issued ``key``, when its shape says so unambiguously."""
    key = key.strip()
    for pattern, provider in _KEY_PATTERNS:
        if pattern.match(key):
            return provider
    return None


def _import_module(name: str) -> ModuleType:
    return importlib.import_module(name)


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


@lru_cache(maxsize=1)
def _warn_generic_sk_key() -> None:
    # Once per process: /status asks on every page load.
    logger.warning(
        "LLM_API_KEY starts with 'sk-' but its provider cannot be told from its shape; "
        "assuming OpenAI. Set LLM_PROVIDER if it belongs to another provider."
    )


def _chat_provider_name(settings: Settings) -> str | None:
    """Explicit LLM_PROVIDER, else what the key says. Validates nothing."""
    explicit = _clean(settings.llm_provider)
    if explicit:
        return explicit.lower()
    key = _clean(settings.llm_api_key)
    if key is None:
        # Old .env files: GOOGLE_API_KEY or OPENAI_API_KEY alone used to mean that provider.
        for name, provider in CHAT_PROVIDERS.items():
            if provider.legacy_key and _clean(getattr(settings, provider.legacy_key)):
                return name
        return None
    detected = detect_provider(key)
    if detected is None and key.startswith("sk-"):
        _warn_generic_sk_key()
        return "openai"
    return detected


def resolve_chat(settings: Settings) -> ChatChoice:
    """Provider, model and key for the chat model, or a message saying what to set."""
    name = _chat_provider_name(settings)
    key = _clean(settings.llm_api_key)
    if name is None:
        if key is None:
            raise MissingProviderError(
                "LLM_API_KEY is not set. Put the API key of your chat provider (Google, "
                "OpenAI, Anthropic, Groq or DeepSeek) in .env or the environment "
                "(see .env.example)."
            )
        raise MissingProviderError(
            "Could not tell which provider issued LLM_API_KEY. Set LLM_PROVIDER to one of: "
            f"{', '.join(CHAT_PROVIDERS)}."
        )
    provider = CHAT_PROVIDERS.get(name)
    if provider is None:
        raise MissingProviderError(
            f"Unknown LLM_PROVIDER {name!r}. Available: {', '.join(CHAT_PROVIDERS)}."
        )
    if key is not None:
        detected = detect_provider(key)
        if detected is not None and detected != name:
            raise MissingProviderError(
                f"LLM_PROVIDER is {name!r} but LLM_API_KEY looks like a {detected!r} key. "
                "Remove LLM_PROVIDER (and LLM_MODEL, if it names a model of the other "
                "provider) to follow the key, or fix the key."
            )
    elif provider.legacy_key:
        key = _clean(getattr(settings, provider.legacy_key))
    if provider.needs_key and key is None:
        raise MissingProviderError(
            f"LLM_API_KEY is not set. Provider {name!r} needs it — put it in .env or the "
            "environment (see .env.example)."
        )
    model = _clean(settings.llm_model) or provider.default_model
    return ChatChoice(provider=name, model=model, key=key if provider.needs_key else None)


def resolve_embeddings(settings: Settings) -> EmbeddingChoice:
    """Provider, model and key for the embeddings, or a message saying what to set."""
    name = (_clean(settings.embedding_provider) or "google").lower()
    provider = EMBEDDING_PROVIDERS.get(name)
    if provider is None:
        raise MissingProviderError(
            f"EMBEDDING_PROVIDER {name!r} has no embeddings here. Available: "
            f"{', '.join(EMBEDDING_PROVIDERS)}."
        )
    key: str | None = None
    if provider.key_setting:
        key = _clean(getattr(settings, provider.key_setting))
        if key is None and _chat_provider_name(settings) == name:
            # One key for both when chat and embeddings come from the same provider.
            key = _clean(settings.llm_api_key)
        if key is None:
            raise MissingProviderError(
                f"{provider.key_env} is not set. Embeddings use EMBEDDING_PROVIDER={name!r} "
                f"and need its key in .env, separate from LLM_API_KEY unless that key is "
                f"also from {name!r} (see .env.example)."
            )
    model = _clean(settings.embedding_model) or provider.default_model
    return EmbeddingChoice(provider=name, model=model, key=key)


def chat_model_name(settings: Settings) -> str:
    """The model the chat runs on, as recorded on each match. Never raises."""
    try:
        return resolve_chat(settings).model
    except MissingProviderError:
        return settings.llm_model or ""


def provider_key_found(settings: Settings) -> bool:
    """True when the chat model can be built as configured. Imports nothing."""
    try:
        resolve_chat(settings)
    except MissingProviderError:
        return False
    return True


def embedding_key_found(settings: Settings) -> bool:
    """True when the embeddings can be built as configured. Imports nothing."""
    try:
        resolve_embeddings(settings)
    except MissingProviderError:
        return False
    return True


def _load(module: str, package: str, label: str) -> ModuleType:
    try:
        return _import_module(module)
    except ImportError as exc:
        raise MissingProviderError(
            f"Provider {label!r} needs the {package} package: pip install {package}"
        ) from exc


def chat_model(settings: Settings) -> BaseChatModel:
    choice = resolve_chat(settings)
    provider = CHAT_PROVIDERS[choice.provider]
    module = _load(provider.module, provider.package, choice.provider)
    factory: Any = getattr(module, provider.chat_class)
    # Models that only accept the default temperature have it dropped by their package.
    kwargs: dict[str, Any] = {"model": choice.model, "temperature": 0}
    if choice.key:
        kwargs["api_key"] = choice.key
    return factory(**kwargs)  # type: ignore[no-any-return]


def embeddings(settings: Settings) -> Embeddings:
    choice = resolve_embeddings(settings)
    provider = EMBEDDING_PROVIDERS[choice.provider]
    module = _load(provider.module, provider.package, choice.provider)
    factory: Any = getattr(module, provider.embeddings_class)
    kwargs: dict[str, Any] = {"model": choice.model}
    if choice.key:
        kwargs["api_key"] = choice.key
    if provider.supports_output_dimensionality:
        kwargs["output_dimensionality"] = settings.embedding_dim
    return factory(**kwargs)  # type: ignore[no-any-return]
