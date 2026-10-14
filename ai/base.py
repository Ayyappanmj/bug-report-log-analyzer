"""AI provider abstraction.

The app must work without any paid API, so the default is NoLLMProvider, which tells the pipeline to stay in
deterministic mode. Real providers live in ollama_provider.py (local, default) and api_provider.py (optional).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from urllib.parse import urlparse


class AIProviderError(Exception):
    """A provider is unavailable or returned an unusable response. `retriable` marks transient failures."""

    def __init__(self, message: str, retriable: bool = False):
        super().__init__(message)
        self.retriable = retriable


class AIProvider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    def is_available(self) -> bool:
        """True if the provider can currently serve requests."""

    def unavailable_reason(self) -> str:
        return "provider is not available"

    @abstractmethod
    def generate(self, prompt: str, system: str | None = None, timeout: float = 60.0) -> str:
        """Return raw model text. Callers must validate it (see ai.validation)."""

    def describe(self) -> str:
        return f"{self.name}:{self.model}" if self.model else self.name


class NoLLMProvider(AIProvider):
    """Deterministic mode: no model is called."""

    name = "none"

    def is_available(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return "no LLM configured (deterministic mode)"

    def generate(self, prompt: str, system: str | None = None, timeout: float = 60.0) -> str:
        raise AIProviderError("No LLM configured; use deterministic analysis mode.")


def validate_base_url(url: str, *, what: str = "URL") -> str:
    """Accept only http(s) URLs with a host; returns the URL without a trailing slash."""
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise AIProviderError(f"Invalid {what}: must start with http:// or https://")
    if parsed.username or parsed.password:
        raise AIProviderError(f"Invalid {what}: credentials in the URL are not allowed")
    return str(url).strip().rstrip("/")


LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


def require_secure_transport(url: str, what: str = "URL") -> None:
    """Credentials may only travel over HTTPS, or over HTTP to this same machine."""
    parsed = urlparse(url)
    if parsed.scheme == "http" and (parsed.hostname or "").lower() not in LOOPBACK_HOSTS:
        raise AIProviderError(f"Refusing to send credentials to {what} over unencrypted HTTP to a non-local host. Use https://")


def get_provider(settings) -> AIProvider:
    """Factory driven by Settings.ai_provider: none | ollama | openai_compatible."""
    kind = (settings.ai_provider or "none").lower()
    if kind == "none":
        return NoLLMProvider()
    if kind == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(settings.ollama_host, settings.ollama_model)
    if kind in ("openai_compatible", "api"):
        from .api_provider import OptionalAPIProvider
        return OptionalAPIProvider(settings.api_base_url, settings.api_key, settings.api_model)
    raise AIProviderError(f"Unknown AI provider '{settings.ai_provider}'. Use none, ollama or openai_compatible.")
