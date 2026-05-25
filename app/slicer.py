"""Drive PrusaSlicer from outside it — there is no plugin API, so we do two things:

1. Headless slice (CLI --export-gcode) to G-code, then parse the header comments
   for the real numbers (print time, filament, layers). These get fed back to
   Claude so it can reason about what a design change will cost.
2. Launch the PrusaSlicer GUI with the model pre-loaded (and a config applied),
   so the user finishes slicing/printing by hand — their existing workflow.
"""

import os
import re
import shutil
import subprocess
import tempfile


def _find_prusa() -> str:
    """Locate the PrusaSlicer CLI across common install layouts."""
    if os.environ.get("PRUSA_BIN"):
        return os.environ["PRUSA_BIN"]
    candidates = [
        "/Applications/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer",
        "/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer",
        shutil.which("prusa-slicer") or "",
        shutil.which("PrusaSlicer") or "",
        "/usr/bin/prusa-slicer",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return candidates[0]  # default; missing-state reported via /api/config


PRUSA_BIN = _find_prusa()

_PATTERNS = {
    "filament_mm":   r"; filament used \[mm\] = ([\d.]+)",
    "filament_cm3":  r"; filament used \[cm3\] = ([\d.]+)",
    "filament_g":    r"; total filament used \[g\] = ([\d.]+)",
    "filament_cost": r"; total filament cost = ([\d.]+)",
    "print_time":    r"; estimated printing time \(normal mode\) = (.+)",
    "layer_height":  r"; layer_height = ([\d.]+)",
    "first_layer":   r"; first_layer_height = ([\d.]+)",
    "fill_density":  r"; fill_density = (\d+%?)",
    "perimeters":    r"; perimeters = (\d+)",
    "nozzle":        r"; nozzle_diameter = ([\d.]+)",
    "printer_model": r"; printer_model = (.*)",
    "supports":      r"; support_material = (\d)",
}


def _time_to_seconds(s: str) -> int:
    total = 0
    for value, unit in re.findall(r"(\d+)\s*([hms])", s):
        total += int(value) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total


def _parse_warnings(text: str) -> list[str]:
    """Pull PrusaSlicer's own print-quality warnings out of its console output.

    These are slicer-authoritative (supports/bridging/stability) — better than a
    geometric heuristic for 'will this print well?'. Progress lines (`69 => ...`)
    are skipped.
    """
    lines = [l.strip() for l in text.splitlines()]
    out: list[str] = []
    i = 0
    while i < len(lines):
        l = lines[i]
        if "Detected print stability issues" in l:
            detail, j = [], i + 1
            while j < len(lines) and "Consider enabling supports" not in lines[j]:
                if lines[j] and not lines[j].lower().endswith(".stl"):
                    detail.append(lines[j])
                j += 1
            msg = "Print stability: " + "; ".join(detail) if detail else "Print stability issues"
            out.append(msg + " — consider supports")
            i = j + 1
            continue
        low = l.lower()
        if (low.startswith("warning:") or low.startswith("print warning")) and not re.match(r"^\d+\s*=>", l):
            out.append(l)
        i += 1
    # dedupe, preserve order
    seen, uniq = set(), []
    for w in out:
        if w not in seen:
            seen.add(w); uniq.append(w)
    return uniq


def slice_stats(stl_path: str, profile_path: str | None = None,
                timeout: int = 180) -> dict:
    """Headless-slice an STL and return parsed print statistics."""
    if not os.path.exists(PRUSA_BIN):
        return {"ok": False, "error": f"PrusaSlicer not found at {PRUSA_BIN}"}

    gcode = tempfile.NamedTemporaryFile(suffix=".gcode", delete=False).name
    cmd = [PRUSA_BIN, "--export-gcode"]
    if profile_path and os.path.exists(profile_path):
        cmd += ["--load", profile_path]
    cmd += [stl_path, "--output", gcode]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"slice timed out after {timeout}s"}

    if not os.path.exists(gcode) or os.path.getsize(gcode) == 0:
        return {"ok": False, "error": (proc.stderr or proc.stdout or "slice failed")[-500:]}

    with open(gcode, errors="ignore") as fh:
        # stats live in the header + footer comments; reading the whole file is fine
        text = fh.read()

    stats: dict = {"ok": True, "gcode_path": gcode}
    for key, pat in _PATTERNS.items():
        m = re.search(pat, text)
        if m:
            stats[key] = m.group(1).strip()
    if "print_time" in stats:
        stats["print_time_s"] = _time_to_seconds(stats["print_time"])
    if stats.get("supports") == "1":
        stats["supports"] = "yes"
    elif stats.get("supports") == "0":
        stats["supports"] = "no"
    used_profile = profile_path and os.path.exists(profile_path)
    stats["profile"] = os.path.basename(profile_path) if used_profile else "generic defaults"
    stats["slicer_warnings"] = _parse_warnings((proc.stdout or "") + "\n" + (proc.stderr or ""))
    return stats


def stats_summary(stats: dict) -> str:
    """One-line human/Claude-readable summary of a slice result."""
    if not stats.get("ok"):
        return f"slice failed: {stats.get('error', 'unknown')}"
    parts = []
    if stats.get("print_time"):
        parts.append(f"print time {stats['print_time']}")
    if stats.get("filament_g") and stats["filament_g"] != "0.00":
        parts.append(f"{stats['filament_g']} g")
    elif stats.get("filament_cm3"):
        parts.append(f"{stats['filament_cm3']} cm3")
    if stats.get("fill_density"):
        parts.append(f"{stats['fill_density']} infill")
    if stats.get("perimeters"):
        parts.append(f"{stats['perimeters']} perimeters")
    if stats.get("layer_height"):
        parts.append(f"{stats['layer_height']}mm layers")
    if stats.get("supports"):
        parts.append(f"supports: {stats['supports']}")
    if stats.get("slicer_warnings"):
        parts.append("slicer warns: " + "; ".join(stats["slicer_warnings"]))
    return ", ".join(parts)


def open_in_slicer(stl_path: str, profile_path: str | None = None) -> dict:
    """Launch the PrusaSlicer GUI with the model loaded and config applied.

    Detached — we don't wait for the GUI to close. This is the hand-off to the
    user's existing slice-and-print workflow.
    """
    if not os.path.exists(PRUSA_BIN):
        return {"ok": False, "error": f"PrusaSlicer not found at {PRUSA_BIN}"}
    cmd = [PRUSA_BIN]
    if profile_path and os.path.exists(profile_path):
        cmd += ["--load", profile_path]
    cmd += [stl_path]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
