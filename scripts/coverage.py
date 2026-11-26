"""Fail if any package under src/ocpp_sdk has line or branch coverage below 95%.

Reads ``coverage.json`` (``pytest --cov=ocpp_sdk --cov-branch --cov-report=json``).
Each directory under ``src/ocpp_sdk`` is one package; ``__init__`` and the
top-level modules form the ``ocpp_sdk`` package itself.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath

THRESHOLD = 95.0


def percent(covered: int, total: int) -> float:
    return 100.0 if total == 0 else 100.0 * covered / total


def main(path: str = "coverage.json") -> int:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for name, info in data["files"].items():
        parts = PurePosixPath(name.replace("\\", "/")).parts
        if "ocpp_sdk" not in parts:
            continue
        idx = len(parts) - 1 - parts[::-1].index("ocpp_sdk")
        pkg = "/".join(parts[idx:-1])
        s = info["summary"]
        t = totals[pkg]
        t[0] += s["covered_lines"]
        t[1] += s["num_statements"]
        t[2] += s.get("covered_branches", 0)
        t[3] += s.get("num_branches", 0)

    failed = False
    for pkg in sorted(totals):
        cl, nl, cb, nb = totals[pkg]
        lines, branches = percent(cl, nl), percent(cb, nb)
        ok = lines >= THRESHOLD and branches >= THRESHOLD
        failed |= not ok
        print(f"{'ok  ' if ok else 'FAIL'} {pkg}: lines {lines:.1f}% branches {branches:.1f}%")
    if not totals:
        print("FAIL: no ocpp_sdk files found in coverage data")
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
