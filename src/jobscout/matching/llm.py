"""Chat model and embeddings, chosen by ``LLM_PROVIDER``.

Providers are imported lazily so the project installs (and its tests run) with only the
default provider present. Keys are read from ``Settings`` (which loads them from ``.env`` or
the real environment) and passed to the provider classes explicitly, rather than relying on
the provider packages' own environment lookups.
"""

import importlib
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from jobscout.config import Settings


class MissingProviderError(RuntimeError):
    """The configured provider is unknown, not installed, or missing its API key."""


@dataclass(frozen=True)
class _Provider:
    module: str
    package: str
    chat_class: str
    embeddings_class: str
    key_setting: str  # Settings attribute name; "" when the provider needs no key
    key_env: str  # env var name to show the user; "" when the provider needs no key
    supports_output_dimensionality: bool = False  # whether API honors output_dimensionality


PROVIDERS: dict[str, _Provider] = {
    "google": _Provider(
        module="langchain_google_genai",
        package="langchain-google-genai",
        chat_class="ChatGoogleGenerativeAI",
        embeddings_class="GoogleGenerativeAIEmbeddings",
        key_setting="google_api_key",
        key_env="GOOGLE_API_KEY",
        supports_output_dimensionality=True,
    ),
    "openai": _Provider(
        module="langchain_openai",
        package="langchain-openai",
        chat_class="ChatOpenAI",
        embeddings_class="OpenAIEmbeddings",
        key_setting="openai_api_key",
        key_env="OPENAI_API_KEY",
    ),
    "ollama": _Provider(
        module="langchain_ollama",
        package="langchain-ollama",
        chat_class="ChatOllama",
        embeddings_class="OllamaEmbeddings",
        key_setting="",  # local server, no key
        key_env="",
    ),
}


def _import_module(name: str) -> ModuleType:
    return importlib.import_module(name)


def _resolve(settings: Settings) -> tuple[_Provider, ModuleType, str | None]:
    provider = PROVIDERS.get(settings.llm_provider)
    if provider is None:
        available = ", ".join(sorted(PROVIDERS))
        raise MissingProviderError(
            f"Unknown LLM_PROVIDER {settings.llm_provider!r}. Available: {available}."
        )
    key: str | None = None
    if provider.key_setting:
        key = getattr(settings, provider.key_setting, None)
        if not key:
            raise MissingProviderError(
                f"{provider.key_env} is not set. Matching needs it for provider "
                f"{settings.llm_provider!r} — put it in .env or the environment "
                "(see .env.example)."
            )
    try:
        module = _import_module(provider.module)
    except ImportError as exc:
        raise MissingProviderError(
            f"Provider {settings.llm_provider!r} needs the {provider.package} package: "
            f"pip install {provider.package}"
        ) from exc
    return provider, module, key


def chat_model(settings: Settings) -> BaseChatModel:
    provider, module, key = _resolve(settings)
    factory: Any = getattr(module, provider.chat_class)
    kwargs: dict[str, Any] = {"model": settings.llm_model, "temperature": 0}
    if key:
        kwargs["api_key"] = key
    return factory(**kwargs)  # type: ignore[no-any-return]


def embeddings(settings: Settings) -> Embeddings:
    provider, module, key = _resolve(settings)
    factory: Any = getattr(module, provider.embeddings_class)
    kwargs: dict[str, Any] = {"model": settings.embedding_model}
    if key:
        kwargs["api_key"] = key
    if provider.supports_output_dimensionality:
        kwargs["output_dimensionality"] = settings.embedding_dim
    return factory(**kwargs)  # type: ignore[no-any-return]
