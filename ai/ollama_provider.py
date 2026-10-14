"""Ollama provider: talks to a local Ollama server over its HTTP API (default http://localhost:11434)."""
from __future__ import annotations

from .base import AIProvider, AIProviderError, validate_base_url
from .http import request_json


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(self, host: str = "http://localhost:11434", model: str = "qwen2.5-coder:7b",
                 temperature: float = 0.0, max_tokens: int = 1500):
        self.host = validate_base_url(host, what="Ollama host")
        self.model = model
        self.temperature, self.max_tokens = temperature, max_tokens
        self._reason = ""

    def list_models(self, timeout: float = 3.0) -> list[str]:
        data = request_json(f"{self.host}/api/tags", timeout=timeout, label="Ollama")
        return [m.get("name", "") for m in data.get("models", []) if isinstance(m, dict)]

    def _has_model(self, installed: list[str]) -> bool:
        want = self.model if ":" in self.model else self.model + ":latest"
        return want in installed or self.model in installed

    def is_available(self) -> bool:
        try:
            installed = self.list_models()
        except AIProviderError as exc:
            self._reason = str(exc)
            return False
        if not self._has_model(installed):
            self._reason = f"model '{self.model}' is not installed (run: ollama pull {self.model})"
            return False
        self._reason = ""
        return True

    def unavailable_reason(self) -> str:
        return self._reason or "Ollama is not available"

    def generate(self, prompt: str, system: str | None = None, timeout: float = 120.0) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        data = request_json(
            f"{self.host}/api/chat", timeout=timeout, label="Ollama",
            payload={"model": self.model, "messages": messages, "stream": False, "format": "json",
                     "options": {"temperature": self.temperature, "num_predict": self.max_tokens}})
        content = (data.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise AIProviderError("Ollama returned an empty response", retriable=True)
        return content
