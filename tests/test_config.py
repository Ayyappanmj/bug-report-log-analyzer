from config import Settings, load_env_file


def test_defaults_without_env():
    s = Settings.from_env(env={})
    assert s.ai_provider == "none" and s.ai_top_n == 3 and s.ai_timeout == 120 and s.redact_emails


def test_env_values_and_bad_numbers():
    s = Settings.from_env(env={"AI_PROVIDER": "OLLAMA", "AI_TOP_N": "5", "AI_TIMEOUT_SECONDS": "abc",
                               "REDACT_EMAILS": "False", "EXCLUDED_DIRS": "a, b"})
    assert (s.ai_provider, s.ai_top_n, s.ai_timeout, s.redact_emails, s.excluded_dirs) == ("ollama", 5, 120, False, ("a", "b"))


def test_env_file_parsing(tmp_path):
    f = tmp_path / ".env"
    f.write_text('# c\nAI_PROVIDER=ollama   # inline\nOLLAMA_MODEL="llama3.1:8b"\nAPI_KEY=\'k#1\'\nbroken line\n\nX=1\n')
    v = load_env_file(f)
    assert v == {"AI_PROVIDER": "ollama", "OLLAMA_MODEL": "llama3.1:8b", "API_KEY": "k#1", "X": "1"}
    assert load_env_file(tmp_path / "missing") == {}
    s = Settings.from_env(env={**v})
    assert s.ai_provider == "ollama" and s.ollama_model == "llama3.1:8b" and s.api_key == "k#1"
