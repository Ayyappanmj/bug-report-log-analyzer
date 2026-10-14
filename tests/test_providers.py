import socket

from pytest import raises

from ai.api_provider import OptionalAPIProvider
from ai.base import AIProviderError
from ai.ollama_provider import OllamaProvider
from tests.fakes import FakeLLMServer


def test_ollama_available_and_generate_payload():
    with FakeLLMServer(replies=['{"a": 1}']) as srv:
        p = OllamaProvider(srv.url, "qwen2.5-coder:7b")
        assert p.is_available()
        assert p.generate("hello", system="be brief", timeout=5) == '{"a": 1}'
    body = next(r["body"] for r in srv.requests if r["path"] == "/api/chat")
    assert body["model"] == "qwen2.5-coder:7b" and body["stream"] is False and body["format"] == "json"
    assert body["options"]["temperature"] == 0
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_ollama_model_matching_and_missing_model_reason():
    with FakeLLMServer(models=("llama3.1:latest",)) as srv:
        assert OllamaProvider(srv.url, "llama3.1").is_available()          # untagged name matches :latest
        p = OllamaProvider(srv.url, "mistral:7b")
        assert not p.is_available() and "ollama pull mistral:7b" in p.unavailable_reason()


def test_ollama_server_down():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    p = OllamaProvider(f"http://127.0.0.1:{port}", "m")
    assert not p.is_available() and "Cannot reach" in p.unavailable_reason()
    with raises(AIProviderError) as ei:
        p.generate("x", timeout=2)
    assert ei.value.retriable


def test_http_errors_are_classified():
    with FakeLLMServer() as srv:
        p = OllamaProvider(srv.url, "qwen2.5-coder:7b")
        srv.status = 500
        with raises(AIProviderError) as e500:
            p.generate("x", timeout=5)
        assert e500.value.retriable and "500" in str(e500.value)
        srv.status = 404
        with raises(AIProviderError) as e404:
            p.generate("x", timeout=5)
        assert not e404.value.retriable


def test_timeout_is_retriable_error():
    with FakeLLMServer() as srv:
        srv.delay = 1.0
        p = OllamaProvider(srv.url, "qwen2.5-coder:7b")
        with raises(AIProviderError) as ei:
            p.generate("x", timeout=0.2)
        assert ei.value.retriable


def test_garbage_and_empty_responses():
    with FakeLLMServer() as srv:
        p = OllamaProvider(srv.url, "qwen2.5-coder:7b")
        srv.raw_body = b"<html>not json</html>"
        with raises(AIProviderError):
            p.generate("x", timeout=5)
        srv.raw_body = None
        srv.replies = ["   "]
        with raises(AIProviderError):
            p.generate("x", timeout=5)


def test_api_provider_sends_key_and_never_leaks_it():
    with FakeLLMServer(replies=['{"x": 2}']) as srv:
        p = OptionalAPIProvider(srv.url + "/v1", "sk-test-SECRET-KEY-000000000000", "gpt-test")
        assert p.generate("hi", system="sys", timeout=5) == '{"x": 2}'
        req = next(r for r in srv.requests if r["path"] == "/v1/chat/completions")
        assert req["headers"]["Authorization"] == "Bearer sk-test-SECRET-KEY-000000000000"
        assert req["body"]["response_format"] == {"type": "json_object"} and req["body"]["model"] == "gpt-test"
        srv.status = 401
        with raises(AIProviderError) as ei:
            p.generate("hi", timeout=5)
        assert "SECRET" not in str(ei.value) and "SECRET" not in repr(p)
        assert not ei.value.retriable


def test_api_provider_without_key_sends_no_auth_header():
    with FakeLLMServer(replies=["{}"]) as srv:
        OptionalAPIProvider(srv.url + "/v1", "", "local-model").generate("hi", timeout=5)
        assert "Authorization" not in next(r for r in srv.requests if r["body"])["headers"]
