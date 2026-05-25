"""OpenSCAD Customizer support: parse `// [..]` annotations into a slider schema,
and re-render the model with overridden values via `openscad -p` (no Claude call).

OpenSCAD 2021.01 has no schema-dump flag, so we parse the annotations ourselves;
value overrides are applied through a customizer parameter set (-p file -P set),
which was verified to override top-level variables cleanly.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile

OPENSCAD = os.environ.get("OPENSCAD_BIN") or shutil.which("openscad") or "/opt/homebrew/bin/openscad"
_LIBS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "libs")
try:
    from compile import MANIFOLD_ARGS  # fast Manifold backend when available
except Exception:  # noqa: BLE001
    MANIFOLD_ARGS = []

# name = value ; // [spec]   spec = min:max | min:step:max | a, b, c
_ANNOT = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*([^;]+?)\s*;\s*//\s*\[([^\]]+)\]", re.M)
_RANGE = re.compile(r"^\s*(-?[\d.]+)\s*:\s*(-?[\d.]+)\s*(?::\s*(-?[\d.]+)\s*)?$")


def _auto_step(lo: float, hi: float) -> float:
    rng = hi - lo
    if rng <= 5:
        return 0.1
    if rng <= 50:
        return 0.5
    return 1.0


def parse_params(scad: str) -> list:
    """Extract slider/choice params from a .scad's inline `// [..]` annotations."""
    params = []
    for name, raw, spec in _ANNOT.findall(scad):
        spec = spec.strip()
        val = raw.strip().strip('"')
        m = _RANGE.match(spec)
        if m:
            a, b, c = m.group(1), m.group(2), m.group(3)
            if c is not None:                 # min:step:max
                lo, step, hi = float(a), float(b), float(c)
            else:                             # min:max
                lo, hi, step = float(a), float(b), None
            try:
                cur = float(val)
            except ValueError:
                cur = lo
            params.append({"name": name, "type": "number", "value": cur,
                           "min": lo, "max": hi, "step": step or _auto_step(lo, hi)})
        else:                                 # choice list
            opts = [o.strip().strip('"') for o in spec.split(",")]
            params.append({"name": name, "type": "choice", "value": val, "options": opts})
    return params


_PART_NAMES = {"show", "part", "parts", "mode", "render", "piece", "component",
               "output", "display", "which", "select"}
_COMBINED = {"all", "both", "everything", "assembly", "combined", "together", "full", "whole"}


def detect_parts(params: list) -> dict | None:
    """Find the choice param that switches between printable parts (e.g. show=box/lid/both).

    A multi-part design is rendered/sliced per part by overriding this one param via -p.
    """
    best = None
    for p in params:
        if p.get("type") != "choice":
            continue
        opts = p.get("options", [])
        if len(opts) < 2:
            continue
        name_ok = p["name"].lower() in _PART_NAMES
        has_combined = any(o.lower() in _COMBINED for o in opts)
        if name_ok or has_combined:
            best = p
            if name_ok and has_combined:
                break
    if not best:
        return None
    return {
        "name": best["name"],
        "current": best.get("value"),
        "options": [{"value": o, "is_combined": o.lower() in _COMBINED} for o in best["options"]],
    }


def render_with_params(scad_path: str, values: dict, out_stl: str,
                       openscadpath: str | None = None, timeout: int = 240):
    """Re-render the .scad with overridden parameter values. Returns (ok, stderr)."""
    pset = {k: str(v) for k, v in values.items()}
    pfile = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    json.dump({"fileFormatVersion": "1", "parameterSets": {"live": pset}}, pfile)
    pfile.close()

    env = os.environ.copy()
    env["OPENSCADPATH"] = openscadpath or os.environ.get("OPENSCADPATH") or _LIBS
    if os.path.exists(out_stl):
        os.remove(out_stl)
    try:
        p = subprocess.run([OPENSCAD, *MANIFOLD_ARGS, "-o", out_stl, "-p", pfile.name, "-P", "live", scad_path],
                           capture_output=True, text=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"re-render timed out after {timeout}s"
    ok = p.returncode == 0 and os.path.exists(out_stl) and os.path.getsize(out_stl) > 200
    return ok, (p.stderr or "")[-500:]
