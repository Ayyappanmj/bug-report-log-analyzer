from pytest import raises

from ai.api_provider import OptionalAPIProvider
from ai.base import AIProviderError, NoLLMProvider, get_provider, validate_base_url
from ai.ollama_provider import OllamaProvider
from config import Settings


def test_default_provider_is_deterministic():
    p = get_provider(Settings())
    assert isinstance(p, NoLLMProvider) and not p.is_available() and "deterministic" in p.unavailable_reason()


def test_no_llm_generate_raises():
    with raises(AIProviderError):
        NoLLMProvider().generate("hi")


def test_factory_builds_real_providers_and_rejects_unknown():
    o = get_provider(Settings(ai_provider="ollama", ollama_host="http://localhost:11434/", ollama_model="m:1b"))
    assert isinstance(o, OllamaProvider) and o.host == "http://localhost:11434" and o.describe() == "ollama:m:1b"
    a = get_provider(Settings(ai_provider="openai_compatible", api_base_url="https://x/v1", api_key="k", api_model="gpt"))
    assert isinstance(a, OptionalAPIProvider) and a.is_available()
    with raises(AIProviderError):
        get_provider(Settings(ai_provider="skynet"))


def test_api_key_not_in_repr():
    assert "secret123" not in repr(Settings(api_key="secret123"))
    p = OptionalAPIProvider("https://x/v1", "secret123", "m")
    assert "secret123" not in repr(p) and "secret123" not in str(p.__dict__.get("model"))


def test_unconfigured_api_provider_is_unavailable_not_crashing():
    p = OptionalAPIProvider("", "", "")
    assert not p.is_available() and "API_BASE_URL" in p.unavailable_reason()
    with raises(AIProviderError):
        p.generate("x")


def test_base_url_validation():
    assert validate_base_url("http://localhost:11434///") == "http://localhost:11434"
    for bad in ("file:///etc/passwd", "ftp://host", "localhost:11434", "http://user:pw@host", ""):
        with raises(AIProviderError):
            validate_base_url(bad)
