"""Headless OpenSCAD: compile .scad -> .stl and render preview PNGs.

This is the deterministic half of the pipeline. The LLM proposes code; OpenSCAD
is the ground truth for whether that code is a real, manifold, printable solid.
A non-zero exit or an empty result is the signal that drives the auto-repair
loop in generate.py.
"""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

OPENSCAD_BIN = os.environ.get("OPENSCAD_BIN") or shutil.which("openscad") or "/opt/homebrew/bin/openscad"

# Make BOSL2 (and any other libs) resolvable for `include <BOSL2/...>`. Harmless
# when unused — points OpenSCAD at <repo>/libs unless OPENSCADPATH is set.
_LIBS = os.environ.get("OPENSCADPATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "libs")
_ENV = {**os.environ, "OPENSCADPATH": _LIBS}


def _manifold_supported() -> bool:
    try:
        h = subprocess.run([OPENSCAD_BIN, "--help"], capture_output=True, text=True, timeout=10)
        return "manifold" in (h.stdout + h.stderr).lower()
    except Exception:  # noqa: BLE001
        return False


# Manifold backend is ~100x faster than CGAL on CSG-heavy parts; use it when the
# installed OpenSCAD supports it (older builds like 2021.01 don't have the flag).
MANIFOLD_ARGS = ["--backend=manifold"] if _manifold_supported() else []

# OpenSCAD prints these to stderr even on a successful (exit 0) export. They
# mean the geometry is suspect and worth flagging back to the user / model.
_WARN_PATTERNS = [
    "may not be a valid 2-manifold",
    "Object may not be a valid",
    "top level object is empty",
    "CGAL error",
    "UI-WARNING",
]


@dataclass
class CompileResult:
    ok: bool
    stl_path: str | None
    stderr: str
    warnings: list[str] = field(default_factory=list)
    returncode: int = 0


def compile_stl(scad_path: str, stl_path: str, timeout: int = 240) -> CompileResult:
    """Render a .scad file to a binary STL. Returns ok=False on any failure."""
    cmd = [OPENSCAD_BIN, *MANIFOLD_ARGS, "-o", stl_path, scad_path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_ENV)
    except subprocess.TimeoutExpired:
        return CompileResult(False, None, f"openscad timed out after {timeout}s", [], -1)
    except FileNotFoundError:
        return CompileResult(False, None, f"openscad binary not found at {OPENSCAD_BIN}", [], -1)

    stderr = proc.stderr or ""
    warnings = [line.strip() for line in stderr.splitlines()
                if any(p in line for p in _WARN_PATTERNS)]

    # An ERROR line means the program didn't compile at all.
    has_error = proc.returncode != 0 or "ERROR:" in stderr

    exists = os.path.exists(stl_path)
    size = os.path.getsize(stl_path) if exists else 0
    # Binary STL header is 84 bytes; anything at/below that is effectively empty.
    empty = size <= 200

    ok = (not has_error) and exists and not empty
    if not ok and not stderr:
        stderr = f"(no stderr) exit={proc.returncode} stl_exists={exists} stl_bytes={size}"
    if empty and exists and not has_error:
        warnings.append(f"STL is effectively empty ({size} bytes)")

    return CompileResult(ok, stl_path if ok else None, stderr, warnings, proc.returncode)


# A couple of fixed camera angles so previews are comparable across parts.
_CAMERAS = [
    ("iso", "55,0,25"),    # rotx,roty,rotz — default-ish 3/4 view
    ("front", "75,0,0"),   # closer to head-on
]


def render_previews(scad_path: str, out_dir: str, basename: str,
                    size: str = "900,700", timeout: int = 120) -> list[str]:
    """Render preview PNGs from a few angles. Best-effort: returns what worked.

    Preview rendering needs offscreen GL and can fail on headless boxes even
    when STL export succeeds, so a failure here never fails the generation.
    """
    pngs: list[str] = []
    for label, rot in _CAMERAS:
        png = os.path.join(out_dir, f"{basename}_{label}.png")
        cmd = [
            OPENSCAD_BIN, *MANIFOLD_ARGS, "-o", png,
            f"--imgsize={size}",
            f"--camera=0,0,0,{rot},0",  # translate=0,0,0 ; rot ; dist=0 (viewall sets it)
            "--viewall", "--autocenter", "--render",
            "--colorscheme=Tomorrow",
            scad_path,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_ENV)
            if proc.returncode == 0 and os.path.exists(png) and os.path.getsize(png) > 0:
                pngs.append(png)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
    return pngs


def openscad_version() -> str:
    try:
        proc = subprocess.run([OPENSCAD_BIN, "--version"],
                              capture_output=True, text=True, timeout=10)
        return (proc.stderr or proc.stdout).strip()
    except Exception as exc:  # noqa: BLE001
        return f"unknown ({exc})"
