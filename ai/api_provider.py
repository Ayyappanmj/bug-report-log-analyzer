"""Optional OpenAI-compatible provider (OpenAI, LM Studio, vLLM, ...). Never required; never logs the key."""
from __future__ import annotations

from .base import AIProvider, AIProviderError, require_secure_transport, validate_base_url
from .http import request_json


class OptionalAPIProvider(AIProvider):
    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str, model: str, temperature: float = 0.0,
                 max_tokens: int = 1500, json_mode: bool = True):
        self._configured = bool(base_url and model)
        self.base_url = validate_base_url(base_url, what="API base URL") if base_url else ""
        self._api_key = api_key or ""
        if self._api_key and self.base_url:
            require_secure_transport(self.base_url, "the API server")
        self.model = model
        self.temperature, self.max_tokens, self.json_mode = temperature, max_tokens, json_mode

    def __repr__(self) -> str:  # never expose the key
        return f"OptionalAPIProvider(base_url={self.base_url!r}, model={self.model!r}, api_key=<hidden>)"

    def is_available(self) -> bool:
        return self._configured

    def unavailable_reason(self) -> str:
        return "API base URL and model must be configured (API_BASE_URL, API_MODEL, API_KEY)"

    def generate(self, prompt: str, system: str | None = None, timeout: float = 60.0) -> str:
        if not self._configured:
            raise AIProviderError(self.unavailable_reason())
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        payload = {"model": self.model, "messages": messages, "temperature": self.temperature, "max_tokens": self.max_tokens}
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        data = request_json(f"{self.base_url}/chat/completions", payload=payload, headers=headers,
                            timeout=timeout, label="API server")
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise AIProviderError("API server returned an unexpected response shape") from None
        if not isinstance(content, str) or not content.strip():
            raise AIProviderError("API server returned an empty response", retriable=True)
        return content
