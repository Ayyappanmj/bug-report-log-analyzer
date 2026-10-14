# Optional LLM integration (Phase 7)

The tool is fully usable without any LLM (deterministic mode). A model can optionally refine the **inference** sections of the
top error groups. It never writes or edits observed evidence.

## How it stays safe
1. The prompt is built from the report's *measured evidence* and real code snippets, not the raw log.
2. Everything is passed through secret redaction (keys, tokens, passwords, JWTs, private keys, URL credentials, emails).
   Redaction is best-effort: do not send confidential logs to a model you do not control.
3. Log/code text is fenced as untrusted data and cannot close the fence; the system prompt tells the model not to follow instructions in it.
4. The reply must be JSON. Format problems (code fences, trailing commas, string-instead-of-list, "85%") are repaired locally.
   The result is validated with Pydantic (`ai/schemas.py: LLMInferenceModel`; a built-in validator with identical rules is used if pydantic is missing).
5. The model must cite evidence ids (E1, E2...) that exist; invented ids are dropped, and a reply citing none is rejected.
6. One corrective retry, then fallback to the unchanged deterministic report with the reason recorded (`ai_fallback_reason`).
7. Warnings (never failures) are attached when the model mentions files that are not in the evidence or writes command-like text.
   Nothing the model returns is ever executed.
8. The model's own confidence is stored separately (`ai_confidence`) and never replaces the heuristic `confidence`.

## Windows setup with Ollama (free, local)
1. Install Ollama from https://ollama.com/download (Windows installer). It runs a local server on http://localhost:11434.
2. In PowerShell: `ollama pull qwen2.5-coder:7b` then `ollama list` to confirm. Smaller models run on weaker machines
   (for example `qwen2.5-coder:3b`); speed and quality depend on your hardware and were not measured for this project.
3. Copy `.env.example` to `.env` and set `AI_PROVIDER=ollama` (and `OLLAMA_MODEL=` if you chose another model).
4. Try it: `python scripts\analyze_cli.py --ai ollama`

## Optional OpenAI-compatible API
Set `AI_PROVIDER=openai_compatible`, `API_BASE_URL`, `API_KEY`, `API_MODEL`. Redacted prompts leave your machine; this is never required.
