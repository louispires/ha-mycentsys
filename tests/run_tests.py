"""Runs every test module without needing pytest.

    python tests/run_tests.py

test_protocol and test_const need nothing installed. test_mqtt_session and
test_cover_logic need homeassistant, paho-mqtt and cryptography.
"""

from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

MODULES = (
    "test_protocol",
    "test_const",
    "test_api_shapes",
    "test_mqtt_session",
    "test_cover_logic",
)


def main() -> int:
    passed = failed = skipped = 0

    for name in MODULES:
        try:
            module = importlib.import_module(name)
        except ImportError as err:
            skipped += 1
            print(f"SKIP {name}: {err}")
            continue

        for attribute in sorted(dir(module)):
            if not attribute.startswith("test_"):
                continue
            try:
                getattr(module, attribute)()
            except Exception:
                failed += 1
                print(f"FAIL {name}.{attribute}")
                traceback.print_exc()
            else:
                passed += 1

    print(f"\n{passed} passed, {failed} failed, {skipped} module(s) skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
