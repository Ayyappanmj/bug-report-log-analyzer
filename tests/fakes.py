"""Test doubles for the LLM layer: a scripted provider and a fake HTTP server (Ollama + OpenAI-compatible)."""
import http.server
import json
import threading
import time

from ai.base import AIProvider


class FakeProvider(AIProvider):
    """Returns scripted replies in order; a reply may be a str or an exception to raise."""

    name, model = "fake", "test"

    def __init__(self, replies, available=True):
        self.replies, self.available, self.calls = list(replies), available, []

    def is_available(self):
        return self.available

    def unavailable_reason(self):
        return "fake provider switched off"

    def generate(self, prompt, system=None, timeout=60.0):
        self.calls.append({"prompt": prompt, "system": system, "timeout": timeout})
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeLLMServer:
    """Serves GET /api/tags, POST /api/chat (Ollama) and POST /v1/chat/completions (OpenAI-style)."""

    def __init__(self, replies=None, models=("qwen2.5-coder:7b",)):
        self.replies = list(replies or ['{"ok": true}'])
        self.models, self.status, self.delay, self.raw_body = list(models), 200, 0.0, None
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": None})
                if self.path == "/api/tags":
                    self._send(outer.status, {"models": [{"name": m} for m in outer.models]})
                else:
                    self._send(404, {})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                if outer.delay:
                    time.sleep(outer.delay)
                if outer.status != 200:
                    return self._send(outer.status, {"error": "boom"})
                if outer.raw_body is not None:
                    return self._send(200, outer.raw_body)
                reply = outer.replies.pop(0) if len(outer.replies) > 1 else outer.replies[0]
                if self.path == "/api/chat":
                    self._send(200, {"message": {"role": "assistant", "content": reply}, "done": True})
                elif self.path == "/v1/chat/completions":
                    self._send(200, {"choices": [{"message": {"role": "assistant", "content": reply}}]})
                else:
                    self._send(404, {})

        class QuietServer(http.server.ThreadingHTTPServer):
            def handle_error(self, request, client_address):  # clients that time out on purpose disconnect early
                pass

        self._server = QuietServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


def good_reply(**overrides) -> str:
    data = {
        "probable_root_cause": "The database connection pool was probably saturated during the burst of requests.",
        "supporting_evidence": ["E1", "E2"], "confidence": 0.7,
        "alternative_possibilities": ["The database server was slow."],
        "recommended_investigation": ["Check pool utilization metrics for the window."],
        "recommended_fix": ["Release connections promptly."], "reproduction_steps": ["Run a load test with a small pool."],
        "inferred_impact": "Checkout requests fail after the timeout.", "caveats": ["No database-side metrics were provided."],
    }
    data.update(overrides)
    return json.dumps(data)


_REPORT = None


def demo_report():
    """Deterministic G001 report for the bundled demo (cached)."""
    global _REPORT
    if _REPORT is None:
        from agent.orchestrator import AnalysisPipeline
        from scripts.generate_demo_log import OUT, SRC
        _REPORT = AnalysisPipeline(top_n=1).run(OUT, SRC.parent).reports["G001"]
    return _REPORT


class FakeJiraServer:
    """Minimal Jira: POST /rest/api/2/issue. `status` and `reply` are configurable; requests are recorded."""

    def __init__(self):
        self.status, self.requests, self.delay = 201, [], 0.0
        self.reply = {"id": "10001", "key": "PAY-12", "self": "x"}
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                outer.requests.append({"path": self.path, "headers": dict(self.headers),
                                       "body": json.loads(self.rfile.read(length) or b"{}")})
                if outer.delay:
                    time.sleep(outer.delay)
                data = json.dumps(outer.reply).encode()
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        class QuietServer(http.server.ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass

        self._server = QuietServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


_RUN = None


def demo_run():
    """Cached deterministic run over the bundled demo (top 8 groups analyzed)."""
    global _RUN
    if _RUN is None:
        from agent.orchestrator import AnalysisPipeline
        from scripts.generate_demo_log import OUT, SRC
        _RUN = AnalysisPipeline(top_n=8).run(OUT, SRC.parent)
    return _RUN


class FakeRedirectServer:
    """Answers every request with a 302 to `location` (used to prove credentials are not forwarded)."""

    def __init__(self, location):
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _redirect(self):
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length:
                    self.rfile.read(length)
                outer.requests.append({"path": self.path, "headers": dict(self.headers)})
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_POST = _redirect

        class Quiet(http.server.ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass

        self._server = Quiet(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
