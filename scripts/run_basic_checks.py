"""Fallback test runner for machines/sandboxes without pytest. Prefer `pytest`.

Provides a minimal stand-in for pytest.raises/importorskip and the tmp_path fixture.
"""
import contextlib
import importlib
import os
import inspect
import sys
import tempfile
import traceback
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class Skip(Exception):
    pass


try:
    import pytest  # noqa: F401
    print("Real pytest is installed: run `pytest` instead of this script.")
except ImportError:
    shim = types.ModuleType("pytest")

    class _ExcInfo:
        value = None

    @contextlib.contextmanager
    def raises(exc):
        info = _ExcInfo()
        try:
            yield info
        except exc as e:
            info.value = e
            return
        raise AssertionError(f"{exc.__name__} not raised")

    def importorskip(name):
        try:
            return importlib.import_module(name)
        except ImportError:
            raise Skip(f"{name} not installed")

    class _Mark:
        def __getattr__(self, name):
            def mark(fn):
                setattr(fn, f"_mark_{name}", True)
                return fn

            def deco(*args, **kwargs):
                if len(args) == 1 and callable(args[0]) and not kwargs:      # bare @pytest.mark.slow
                    return mark(args[0])
                if name == "skipif" and args and args[0]:                    # @pytest.mark.skipif(True, reason=...)
                    return lambda fn: mark(fn) and setattr(fn, "_mark_skip", True) or fn
                return lambda fn: fn
            return deco

    shim.raises, shim.importorskip, shim.mark = raises, importorskip, _Mark()
    sys.modules["pytest"] = shim

def main() -> int:
    passed = failed = skipped = 0
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        try:
            mod = importlib.import_module(f"tests.{path.stem}")
        except Skip as e:
            print(f"SKIP {path.stem}: {e}")
            skipped += 1
            continue
        for name, fn in sorted(vars(mod).items()):
            if not (name.startswith("test_") and callable(fn)):
                continue
            if getattr(fn, "_mark_skip", False) or (os.environ.get("SKIP_SLOW") and getattr(fn, "_mark_slow", False)):
                skipped += 1
                continue
            try:
                if "tmp_path" in inspect.signature(fn).parameters:
                    with tempfile.TemporaryDirectory() as d:
                        fn(Path(d))
                else:
                    fn()
                passed += 1
            except Skip as e:
                skipped += 1
                print(f"SKIP {path.stem}::{name}: {e}")
            except Exception:
                failed += 1
                print(f"FAIL {path.stem}::{name}")
                traceback.print_exc()
    print(f"{passed} passed, {failed} failed, {skipped} modules skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
