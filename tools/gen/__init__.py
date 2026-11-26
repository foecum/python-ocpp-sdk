"""Code generator: official schemas and ``profiles.py`` -> ``src/ocpp_sdk/<version>/``.

Run ``uv run python -m tools.gen`` after changing the generator, its tables or the
schemas. ``generate()`` returns the files (path -> text) without writing them;
``tests/unit/test_generated_up_to_date.py`` compares them with what is committed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.gen import appendices, emit, handlers, schema
from tools.gen.profiles import V16, V201, Profile

ROOT = schema.ROOT
SRC = ROOT / "src" / "ocpp_sdk"

PROFILES: tuple[Profile, ...] = (V16, V201)


def _format(path: str, source: str) -> str:
    """Sort imports, drop unused ones and format, as the rest of the code base."""
    base = [sys.executable, "-m", "ruff"]
    fixed = subprocess.run(
        [*base, "check", "--fix", "--select", "I,F401", "--quiet", "--stdin-filename", path, "-"],
        input=source,
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if fixed.returncode not in (0, 1):
        raise RuntimeError(fixed.stderr)
    done = subprocess.run(
        [*base, "format", "--stdin-filename", path, "-"],
        input=fixed.stdout,
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    )
    return done.stdout


def generate() -> dict[Path, str]:
    """Render every generated file."""
    files: dict[Path, str] = {}
    for profile in PROFILES:
        ir = schema.load(profile)
        out = SRC / profile.package
        files[out / "types.py"] = emit.render_types(profile, ir)
        for module in profile.modules:
            files[out / f"{module.name}.py"] = emit.render_module(
                profile, ir, module.name, module.title
            )
        for side in handlers.SIDES:
            prefix = profile.station_module if side == "charge_point" else side
            files[out / f"{prefix}_handlers.py"] = handlers.render(profile, ir, side)
        if profile.appendices_dir:
            files[out / "appendices.py"] = appendices.render(profile)
    return {p: _format(str(p.relative_to(ROOT)), text) for p, text in files.items()}


def write() -> list[Path]:
    """Write the generated files; returns the paths."""
    files = generate()
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return list(files)
