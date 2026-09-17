"""Simple test runner (no pytest required)."""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "pandemic_bankers"))

passed = 0
failed = 0

for fname in sorted(os.listdir(os.path.dirname(__file__))):
    if not fname.startswith("test_") or not fname.endswith(".py"):
        continue
    spec = importlib.util.spec_from_file_location(fname, os.path.join(os.path.dirname(__file__), fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in dir(mod):
        if name.startswith("test_"):
            try:
                getattr(mod, name)()
                print(f"PASS  {fname}::{name}")
                passed += 1
            except Exception as exc:
                print(f"FAIL  {fname}::{name}  ->  {exc}")
                failed += 1

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
