"""Benchmark scenarios: small projects + logs with a known ground truth.

Scenario 1 is the bundled demo. Scenarios 2-4 are generated here (deterministic). Each has a `truth` describing the real
root cause, so a run can be checked objectively: did the tool find the right exception, raise site and source line?
All scenarios are SYNTHETIC: results say how the tool behaves on these, not on real production logs.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INVENTORY = '''"""Stock reservation."""


class Inventory:
    def __init__(self, store):
        self.store = store

    def find_item(self, sku):
        return self.store.get(sku)

    def reserve(self, sku, qty):
        item = self.find_item(sku)
        if item.quantity < qty:
            raise ValueError("insufficient stock")
        item.quantity -= qty
        return item
'''
ORDERS = '''"""Order placement."""
from inventory import Inventory


class OrderService:
    def __init__(self, inventory: Inventory):
        self.inventory = inventory

    def place_order(self, sku, qty):
        reserved = self.inventory.reserve(sku, qty)
        return {"sku": sku, "reserved": reserved.quantity}
'''
REPORT_CLIENT = '''"""Client for the internal reporting service."""
import socket


class ReportClient:
    def __init__(self, host, timeout=10.0):
        self.host = host
        self.timeout = timeout

    def fetch(self, report_id):
        sock = socket.create_connection((self.host, 443), timeout=self.timeout)
        try:
            sock.sendall(f"GET /reports/{report_id}".encode())
            return sock.recv(65536)
        finally:
            sock.close()
'''
EXPORTER = '''"""Exports reports to CSV."""
from report_client import ReportClient


class Exporter:
    def __init__(self, client: ReportClient):
        self.client = client

    def export(self, report_id):
        data = self.client.fetch(report_id)
        return data.decode("utf-8")
'''
CONFIG_LOADER = '''"""Configuration loading."""
import json


def load_config(path):
    with open(path) as fh:
        return json.load(fh)
'''
MAIN = '''"""Service entry point."""
from config_loader import load_config


def start():
    config = load_config("/etc/app/config.json")
    return config["port"]
'''


@dataclass
class Scenario:
    name: str
    title: str
    task: str                                    # what a human investigator is asked to find
    truth: dict                                  # exception_type, file, function, marker (text of the failing line), rule_id
    project_dir: Path
    log_path: Path
    incident_events: int = 0
    log_lines: int = 0


@dataclass
class _Spec:
    name: str
    title: str
    task: str
    files: dict
    frames: list                                 # (relative path, marker, function), outermost -> innermost
    exception: str                               # may contain {n}
    service: str
    message: str                                 # may contain {n}
    incidents: int
    truth: dict
    level: str = "ERROR"
    precursor: str | None = None


SPECS = [
    _Spec("inventory_nullref", "Orders fail with an AttributeError", "Find why order placement fails for some products.",
          {"src/inventory.py": INVENTORY, "src/orders.py": ORDERS},
          [("src/orders.py", "self.inventory.reserve(", "place_order"), ("src/inventory.py", "if item.quantity < qty:", "reserve")],
          "AttributeError: 'NoneType' object has no attribute 'quantity'", "OrderService", "Order placement failed sku=SKU-{n}", 35,
          {"exception_type": "AttributeError", "file": "src/inventory.py", "function": "reserve", "marker": "item.quantity < qty",
           "rule_id": "null_reference"}),
    _Spec("report_timeout", "Report exports hang then fail", "Find why report exports fail in the afternoon.",
          {"src/report_client.py": REPORT_CLIENT, "src/exporter.py": EXPORTER},
          [("src/exporter.py", "self.client.fetch(", "export"), ("src/report_client.py", "socket.create_connection(", "fetch")],
          "TimeoutError: timed out after 10.0s connecting to reports.internal:443", "Exporter", "Report export failed report={n}", 60,
          {"exception_type": "TimeoutError", "file": "src/report_client.py", "function": "fetch", "marker": "socket.create_connection(",
           "rule_id": "generic_timeout"}),
    _Spec("config_missing", "Service crash-loops on startup", "Find why the service keeps restarting.",
          {"src/config_loader.py": CONFIG_LOADER, "src/main.py": MAIN},
          [("src/main.py", 'load_config("/etc/app/config.json")', "start"), ("src/config_loader.py", "with open(path) as fh:", "load_config")],
          "FileNotFoundError: [Errno 2] No such file or directory: '/etc/app/config.json'", "Launcher", "Service failed to start attempt={n}", 25,
          {"exception_type": "FileNotFoundError", "file": "src/config_loader.py", "function": "load_config", "marker": "with open(path) as fh:",
           "rule_id": "file_missing"}, level="CRITICAL"),
]

DEMO_TRUTH = {"exception_type": "DatabaseConnectionTimeout", "file": "src/database.py", "function": "_acquire_connection",
              "marker": "raise DatabaseConnectionTimeout(", "rule_id": "db_pool_timeout"}
DEMO_TASK = "Find why checkouts fail between 10:20 and 10:34."


def _frame(src_root: Path, rel: str, marker: str, func: str) -> str:
    lines = (src_root / rel).read_text(encoding="utf-8").splitlines()
    hits = [i for i, l in enumerate(lines, 1) if marker in l]
    if len(hits) != 1:
        raise ValueError(f"marker {marker!r} matched {len(hits)} times in {rel}")
    return f'  File "{rel}", line {hits[0]}, in {func}\n    {lines[hits[0] - 1].strip()}'


def _write_scenario(spec: _Spec, out_dir: Path, seed: int) -> Scenario:
    proj = out_dir / spec.name / "project"
    for rel, text in spec.files.items():
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    rng = random.Random(seed)
    events: list[tuple[datetime, str]] = []
    t0 = datetime(2026, 9, 30, 9, 0, 0)
    for i in range(1500):                                            # background traffic
        ts = t0 + timedelta(seconds=i * 2, milliseconds=rng.randint(0, 900))
        rid = f"{rng.getrandbits(24):06x}"
        events.append((ts, f"{ts:%Y-%m-%d %H:%M:%S},{ts.microsecond // 1000:03d} INFO  [Gateway] [Thread-{rng.randint(1, 8)}] [req={rid}] "
                           f"GET /api/items/{rng.randint(1, 9999)} 200 {rng.randint(5, 300)}ms"))
    start = t0 + timedelta(minutes=rng.randint(20, 40))
    for i in range(spec.incidents):
        ts = start + timedelta(seconds=i * rng.randint(3, 20))
        rid = f"{rng.getrandbits(24):06x}"
        tb = "Traceback (most recent call last):\n" + "\n".join(_frame(proj, *f) for f in spec.frames) + "\n" + spec.exception.format(n=i)
        events.append((ts, f"{ts:%Y-%m-%d %H:%M:%S},{ts.microsecond // 1000:03d} {spec.level:<5} [{spec.service}] [Thread-3] [req={rid}] "
                           f"{spec.message.format(n=rng.randint(1000, 99999))}\n{tb}"))
    events.sort(key=lambda e: e[0])
    log = out_dir / spec.name / "app.log"
    log.write_text("\n".join(e[1] for e in events) + "\n", encoding="utf-8", newline="\n")
    return Scenario(spec.name, spec.title, spec.task, spec.truth, proj, log, spec.incidents, log.read_text(encoding="utf-8").count("\n"))


def build_scenarios(out_dir, seed: int = 2026) -> list[Scenario]:
    """Write scenarios 2-4 into `out_dir` and return all four (scenario 1 is the bundled demo)."""
    out_dir = Path(out_dir)
    demo = Scenario("demo_db_pool", "Checkout fails during a database timeout burst", DEMO_TASK, DEMO_TRUTH,
                    ROOT / "demo" / "project", ROOT / "demo" / "logs" / "production_sample.log")
    return [demo] + [_write_scenario(s, out_dir, seed + i) for i, s in enumerate(SPECS)]


def check_truth(run, truth: dict) -> dict:
    """Objective check of a finished AnalysisRun against a scenario's ground truth."""
    groups = run.grouping.groups
    match = next((g for g in groups if g.exception_type == truth["exception_type"] and g.kind == "exception"), None)
    out = {"group_found": match is not None, "group_rank": None, "raise_site_correct": False, "code_verified_at_truth": False,
           "rule_correct": False, "failing_line_shown": False}
    if match is None:
        return out
    out["group_rank"] = groups.index(match) + 1
    out["raise_site_correct"] = (match.raise_site or "").endswith(f"{truth['file']}:{truth['function']}")
    rep = run.reports.get(match.id)
    if rep is not None:
        out["rule_correct"] = rep.rule_id == truth["rule_id"]
        for c in rep.code_context:
            if c["file_path"] == truth["file"] and c["verified"] and (c["qualname"] or "").endswith(truth["function"]):
                out["code_verified_at_truth"] = True
                out["failing_line_shown"] = truth["marker"] in (c["snippet"] or "")
    out["all_correct"] = all(out[k] for k in ("group_found", "raise_site_correct", "code_verified_at_truth", "rule_correct", "failing_line_shown"))
    return out
