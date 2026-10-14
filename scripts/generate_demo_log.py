"""Deterministically generate demo/logs/production_sample.log (synthetic data).

Stack-trace line numbers and code text are looked up in the real demo source files,
so the log always matches demo/project/src. Run: python scripts/generate_demo_log.py
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "demo" / "project" / "src"
OUT = ROOT / "demo" / "logs" / "production_sample.log"
SEED = 42


def _find(filename: str, marker: str) -> tuple[int, str]:
    lines = (SRC / filename).read_text(encoding="utf-8").splitlines()
    hits = [i for i, l in enumerate(lines, 1) if marker in l]
    if len(hits) != 1:
        raise ValueError(f"marker {marker!r} matched {len(hits)} times in {filename}")
    return hits[0], lines[hits[0] - 1].strip()


def _frame(filename: str, marker: str, func: str) -> str:
    n, code = _find(filename, marker)
    return f'  File "src/{filename}", line {n}, in {func}\n    {code}'


def _timeout_chain(order: str) -> str:
    tb1 = "\n".join([
        "Traceback (most recent call last):",
        _frame("checkout.py", "self.payments.charge(", "process_checkout"),
        _frame("payment_service.py", "result = self.db.execute(", "charge"),
        _frame("database.py", "self._acquire_connection()", "execute"),
        _frame("database.py", "raise DatabaseConnectionTimeout(", "_acquire_connection"),
        "DatabaseConnectionTimeout: Timed out after 5.0s waiting for a connection (pool_size=10)",
    ])
    tb2 = "\n".join([
        "Traceback (most recent call last):",
        _frame("checkout.py", "raise CheckoutError(", "process_checkout"),
        f"CheckoutError: Payment could not be completed for order {order}",
    ])
    return (tb1 + "\n\nThe above exception was the direct cause of the following exception:\n\n" + tb2)


def _keyerror_tb() -> str:
    return "\n".join([
        "Traceback (most recent call last):",
        _frame("checkout.py", 'currency = order["currency"]', "process_checkout"),
        "KeyError: 'currency'",
    ])


def build_log(seed: int = SEED) -> str:
    rng = random.Random(seed)
    start = datetime(2026, 9, 30, 9, 55, 0)
    end = datetime(2026, 9, 30, 10, 45, 0)
    inc_start, inc_end = datetime(2026, 9, 30, 10, 20), datetime(2026, 9, 30, 10, 34)
    pre_start = datetime(2026, 9, 30, 10, 12)
    entries: list[tuple[datetime, int, str]] = []

    def raw(ts: datetime, text: str) -> None:
        entries.append((ts, len(entries), text))

    def add(ts, level, service, thread, rid, msg, extra=None) -> None:
        text = (f"{ts:%Y-%m-%d %H:%M:%S},{ts.microsecond // 1000:03d} {level:<5} "
                f"[{service}] [{thread}] [req={rid}] {msg}")
        raw(ts, text + ("\n" + extra if extra else ""))

    def gateway_json(ts, rid, status, ms) -> None:
        raw(ts, json.dumps({"ts": ts.isoformat(timespec="milliseconds"), "level": "error",
                            "service": "api-gateway", "request_id": rid,
                            "msg": "upstream returned error", "status": status, "duration_ms": ms}))

    raw(start, f"{start:%Y-%m-%d %H:%M:%S},000 INFO  [Application] [MainThread] [req=-] "
               "Starting checkout-app version=2.4.1 env=staging-sim")
    hc = start
    while hc < end:
        if hc == datetime(2026, 9, 30, 10, 28, 0):
            add(hc, "CRITICAL", "HealthCheck", "Thread-1", "-",
                "Readiness probe failed db=down; instance marked unhealthy")
        else:
            add(hc, "DEBUG", "HealthCheck", "Thread-1", "-", "health ok db=up cache=up")
        hc += timedelta(seconds=30)

    t, oid = start + timedelta(seconds=1), 1001
    while t < end:
        t += timedelta(seconds=rng.randint(1, 4), milliseconds=rng.randint(0, 999))
        oid += 1
        order, th, rid = f"ORD-{oid}", f"Thread-{rng.randint(2, 12)}", f"{rng.getrandbits(24):06x}"
        add(t, "INFO", "CheckoutService", th, rid, f"Checkout started order={order} user=u{rng.randint(100, 999)}")
        in_pre = pre_start <= t < inc_start
        if in_pre and rng.random() < 0.4:
            add(t + timedelta(milliseconds=30), "WARN", "Database", th, rid,
                f"Connection pool utilization at {rng.randint(88, 100)}%")
        if in_pre and rng.random() < 0.4:
            add(t + timedelta(milliseconds=60), "WARN", "PaymentService", th, rid,
                f"Slow database call {rng.randint(1200, 3500)}ms order={order}")
        if inc_start <= t < inc_end and rng.random() < 0.6:
            fail = t + timedelta(seconds=5, milliseconds=rng.randint(0, 60))
            add(fail, "ERROR", "PaymentService", th, rid,
                f"Database connection timeout while charging order={order} (waited 5.0s)")
            add(fail + timedelta(milliseconds=2), "ERROR", "CheckoutService", th, rid,
                f"Checkout failed for order={order}", _timeout_chain(order))
            gateway_json(fail + timedelta(milliseconds=8), rid, 500, 5000 + rng.randint(0, 80))
        else:
            add(t + timedelta(milliseconds=80), "INFO", "PaymentService", th, rid,
                f"Charge succeeded order={order} amount={rng.randint(500, 20000) / 100:.2f}")
            add(t + timedelta(milliseconds=150), "INFO", "api-gateway", th, rid,
                f"POST /api/checkout 200 {rng.randint(90, 400)}ms")

    for minute in (5, 27, 41):  # unrelated, rarer incident: missing currency field
        ts = datetime(2026, 9, 30, 10, minute, rng.randint(0, 59), rng.randint(0, 999) * 1000)
        oid += 1
        order, rid = f"ORD-{oid}", f"{rng.getrandbits(24):06x}"
        add(ts, "ERROR", "CheckoutService", "Thread-4", rid,
            f"Checkout failed for order={order}: invalid order payload", _keyerror_tb())
        gateway_json(ts + timedelta(milliseconds=5), rid, 500, rng.randint(8, 30))

    for _ in range(12):  # auth noise
        ts = start + timedelta(seconds=rng.randint(5, 2990), milliseconds=rng.randint(0, 999))
        rid = f"{rng.getrandbits(24):06x}"
        add(ts, "WARN", "AuthService", "Thread-6", rid,
            f"Invalid token for user=u{rng.randint(100, 999)} from ip=10.0.{rng.randint(0, 9)}.{rng.randint(1, 250)}")
        add(ts + timedelta(milliseconds=3), "INFO", "api-gateway", "Thread-6", rid, "POST /api/checkout 401 4ms")

    rot = datetime(2026, 9, 30, 10, 10, 0)
    raw(rot, "-- log rotated --")
    raw(rot + timedelta(milliseconds=1), "Connection reset by peer")

    entries.sort(key=lambda e: (e[0], e[1]))
    return "\n".join(e[2] for e in entries) + "\n"


def main() -> None:
    text = build_log()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    lines = text.splitlines()
    print(f"Wrote {OUT} ({len(lines)} lines, {len(text.encode()) / 1024:.1f} KB)")
    print(f"Plain-text ERROR lines: {sum(' ERROR ' in l for l in lines)}")


if __name__ == "__main__":
    main()
