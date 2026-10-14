"""Deterministic synthetic log generator for benchmarks.

The mix is realistic enough to exercise every stage: INFO traffic, WARN pressure signals, chained tracebacks that point at the
real demo source (so code retrieval is exercised), JSON gateway errors, and unique-but-similar noise errors. The generator returns
the exact number of events it wrote per template so a benchmark can check the OUTPUT is correct, not just fast.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from scripts.generate_demo_log import _keyerror_tb, _timeout_chain


@dataclass
class GenerationInfo:
    path: Path
    bytes_written: int = 0
    lines: int = 0
    events: int = 0
    counts: dict = field(default_factory=dict)      # template name -> number of problem events written

    @property
    def megabytes(self) -> float:
        return self.bytes_written / (1024 * 1024)

    @property
    def expected_group_counts(self) -> list[int]:
        return sorted(v for v in self.counts.values() if v)


def generate_log(path, target_mb: float, seed: int = 2026) -> GenerationInfo:
    rng = random.Random(seed)
    path = Path(path)
    info = GenerationInfo(path=path, counts={k: 0 for k in ("db_timeout_chain", "payment_error", "keyerror", "noise_error",
                                                            "gateway_json", "slow_warn", "pool_warn")})
    target = int(target_mb * 1024 * 1024)
    t = datetime(2026, 9, 30, 0, 0, 0)
    n = 0

    def fmt(ts, level, svc, thread, rid, msg):
        return f"{ts:%Y-%m-%d %H:%M:%S},{ts.microsecond // 1000:03d} {level:<5} [{svc}] [Thread-{thread}] [req={rid}] {msg}"

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        def emit(text):
            f.write(text + "\n")
            info.bytes_written += len(text.encode("utf-8")) + 1
            info.lines += text.count("\n") + 1
        while info.bytes_written < target:
            n += 1
            t += timedelta(milliseconds=rng.randint(5, 400))
            rid, th, oid = f"{rng.getrandbits(24):06x}", rng.randint(1, 12), f"ORD-{n}"
            r = rng.random()
            if r < 0.025:
                emit(fmt(t, "ERROR", "PaymentService", th, rid, f"Database connection timeout while charging order={oid} (waited 5.0s)"))
                emit(fmt(t, "ERROR", "CheckoutService", th, rid, f"Checkout failed for order={oid}") + "\n" + _timeout_chain(oid))
                emit('{"ts": "%s", "level": "error", "service": "api-gateway", "request_id": "%s", "msg": "upstream returned error", "status": 500}'
                     % (t.isoformat(timespec="milliseconds"), rid))
                info.events += 3
                info.counts["payment_error"] += 1
                info.counts["db_timeout_chain"] += 1
                info.counts["gateway_json"] += 1
            elif r < 0.03:
                emit(fmt(t, "ERROR", "CheckoutService", th, rid, f"Checkout failed for order={oid}: invalid order payload") + "\n" + _keyerror_tb())
                info.events += 1
                info.counts["keyerror"] += 1
            elif r < 0.045:
                emit(fmt(t, "ERROR", "Inventory", th, rid, f"Upstream lookup failed for tenant=T{rng.randint(1, 99999)} after {rng.randint(1, 900)}ms"))
                info.events += 1
                info.counts["noise_error"] += 1
            elif r < 0.07:
                emit(fmt(t, "WARN", "PaymentService", th, rid, f"Slow database call {rng.randint(1200, 4900)}ms order={oid}"))
                info.events += 1
                info.counts["slow_warn"] += 1
            elif r < 0.085:
                emit(fmt(t, "WARN", "Database", th, rid, f"Connection pool utilization at {rng.randint(88, 100)}%"))
                info.events += 1
                info.counts["pool_warn"] += 1
            else:
                emit(fmt(t, "INFO", "CheckoutService", th, rid, f"Checkout started order={oid} user=u{rng.randint(100, 9999)}"))
                emit(fmt(t, "INFO", "api-gateway", th, rid, f"POST /api/checkout 200 {rng.randint(40, 600)}ms"))
                info.events += 2
    return info
