"""Central configuration. Values come from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_EXCLUDED_DIRS = (
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".idea", ".vscode",
)
TOOL_VERSION = "1.0.0-rc1"
ALLOWED_LOG_EXTENSIONS = (".log", ".txt", ".json", ".jsonl")


def _int(env, name: str, default: int) -> int:
    try:
        return int(env.get(name, default))
    except (TypeError, ValueError):
        return default


def load_env_file(path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file (comments, quotes, inline ' #' comments). Missing file -> {}."""
    values: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if val[:1] in ("'", '"') and val.endswith(val[:1]) and len(val) >= 2:
            val = val[1:-1]
        else:
            val = val.split(" #", 1)[0].strip()
        values[key.strip()] = val
    return values


@dataclass(frozen=True)
class Settings:
    ai_provider: str = "none"  # none | ollama | openai_compatible
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    api_base_url: str = ""
    api_key: str = field(default="", repr=False)  # never printed
    api_model: str = ""
    ai_timeout: int = 120
    ai_top_n: int = 3
    redact_emails: bool = True
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = field(default="", repr=False)  # never printed
    jira_project_key: str = ""
    jira_issue_type: str = "Bug"
    jira_auth: str = "basic"  # basic (Cloud: email + API token) | bearer (Server/DC personal access token)
    store_history: bool = True
    public_demo: bool = False          # shared/hosted demo: no local paths, history, Jira, or LLM
    allow_local_paths: bool = True
    allowed_roots: tuple[str, ...] = ()
    max_log_size_mb: int = 50
    excluded_dirs: tuple[str, ...] = DEFAULT_EXCLUDED_DIRS
    db_path: Path = Path("storage/history.db")

    @classmethod
    def from_env(cls, env=None, env_file=None) -> "Settings":
        """Real environment variables win over values from the .env file (default: <project root>/.env)."""
        if env is None:
            file_values = load_env_file(env_file or Path(__file__).resolve().parent / ".env")
            env = {**file_values, **os.environ}
        excluded = env.get("EXCLUDED_DIRS")
        return cls(
            ai_provider=env.get("AI_PROVIDER", "none").lower(),
            ollama_host=env.get("OLLAMA_HOST", cls.ollama_host),
            ollama_model=env.get("OLLAMA_MODEL", cls.ollama_model),
            api_base_url=env.get("API_BASE_URL", ""),
            api_key=env.get("API_KEY", ""),
            api_model=env.get("API_MODEL", ""),
            ai_timeout=_int(env, "AI_TIMEOUT_SECONDS", 120),
            ai_top_n=_int(env, "AI_TOP_N", 3),
            redact_emails=str(env.get("REDACT_EMAILS", "true")).lower() != "false",
            jira_base_url=env.get("JIRA_BASE_URL", ""),
            jira_email=env.get("JIRA_EMAIL", ""),
            jira_api_token=env.get("JIRA_API_TOKEN", ""),
            jira_project_key=env.get("JIRA_PROJECT_KEY", ""),
            jira_issue_type=env.get("JIRA_ISSUE_TYPE", "Bug"),
            jira_auth=env.get("JIRA_AUTH", "basic").lower(),
            store_history=str(env.get("STORE_HISTORY", "true")).lower() != "false",
            public_demo=str(env.get("PUBLIC_DEMO", "false")).lower() == "true",
            allow_local_paths=str(env.get("ALLOW_LOCAL_PATHS", "true")).lower() != "false",
            allowed_roots=tuple(x.strip() for x in str(env.get("ALLOWED_ROOTS", "")).split(os.pathsep) if x.strip()),
            max_log_size_mb=_int(env, "MAX_LOG_SIZE_MB", 50),
            excluded_dirs=tuple(x.strip() for x in excluded.split(",") if x.strip())
            if excluded else DEFAULT_EXCLUDED_DIRS,
            db_path=Path(env.get("DB_PATH", "storage/history.db")),
        )

    # ---- effective permissions (public-demo mode switches the risky features off)
    @property
    def local_paths_allowed(self) -> bool:
        return self.allow_local_paths and not self.public_demo

    @property
    def history_enabled(self) -> bool:
        return self.store_history and not self.public_demo

    @property
    def jira_enabled(self) -> bool:
        return not self.public_demo

    @property
    def ai_allowed(self) -> bool:
        return not self.public_demo

    def path_policy(self):
        from security.policy import PathPolicy
        return PathPolicy(self.local_paths_allowed, self.allowed_roots)


SAFE_OVERRIDES = ("ai_top_n", "max_log_size_mb", "ollama_model", "redact_emails", "store_history")


def apply_overrides(base: Settings, overrides: dict) -> Settings:
    """Session overrides from the Settings page. Only whitelisted keys, clamped; hosts, keys and modes can never be overridden."""
    import dataclasses
    clean = {k: v for k, v in (overrides or {}).items() if k in SAFE_OVERRIDES}
    if "ai_top_n" in clean:
        clean["ai_top_n"] = max(0, min(int(clean["ai_top_n"]), 8))
    if "max_log_size_mb" in clean:
        cap = base.max_log_size_mb if base.public_demo else 500
        clean["max_log_size_mb"] = max(1, min(int(clean["max_log_size_mb"]), cap))
    if "store_history" in clean and base.public_demo:
        clean["store_history"] = False
    if "ollama_model" in clean:
        clean["ollama_model"] = str(clean["ollama_model"])[:100]
    return dataclasses.replace(base, **clean)
