"""Chat model and embeddings, chosen by ``LLM_PROVIDER``.

Providers are imported lazily so the project installs (and its tests run) with only the
default provider present. Keys are read from the environment by the provider packages.
"""

import importlib
import os
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
    key_env: str


PROVIDERS: dict[str, _Provider] = {
    "google": _Provider(
        module="langchain_google_genai",
        package="langchain-google-genai",
        chat_class="ChatGoogleGenerativeAI",
        embeddings_class="GoogleGenerativeAIEmbeddings",
        key_env="GOOGLE_API_KEY",
    ),
    "openai": _Provider(
        module="langchain_openai",
        package="langchain-openai",
        chat_class="ChatOpenAI",
        embeddings_class="OpenAIEmbeddings",
        key_env="OPENAI_API_KEY",
    ),
    "ollama": _Provider(
        module="langchain_ollama",
        package="langchain-ollama",
        chat_class="ChatOllama",
        embeddings_class="OllamaEmbeddings",
        key_env="",  # local server, no key
    ),
}


def _import_module(name: str) -> ModuleType:
    return importlib.import_module(name)


def _resolve(settings: Settings) -> tuple[_Provider, ModuleType]:
    provider = PROVIDERS.get(settings.llm_provider)
    if provider is None:
        available = ", ".join(sorted(PROVIDERS))
        raise MissingProviderError(
            f"Unknown LLM_PROVIDER {settings.llm_provider!r}. Available: {available}."
        )
    if provider.key_env and not os.environ.get(provider.key_env):
        raise MissingProviderError(
            f"{provider.key_env} is not set. Matching needs it for provider "
            f"{settings.llm_provider!r} — see .env.example."
        )
    try:
        module = _import_module(provider.module)
    except ImportError as exc:
        raise MissingProviderError(
            f"Provider {settings.llm_provider!r} needs the {provider.package} package: "
            f"pip install {provider.package}"
        ) from exc
    return provider, module


def chat_model(settings: Settings) -> BaseChatModel:
    provider, module = _resolve(settings)
    factory: Any = getattr(module, provider.chat_class)
    return factory(model=settings.llm_model, temperature=0)  # type: ignore[no-any-return]


def embeddings(settings: Settings) -> Embeddings:
    provider, module = _resolve(settings)
    factory: Any = getattr(module, provider.embeddings_class)
    return factory(model=settings.embedding_model)  # type: ignore[no-any-return]
