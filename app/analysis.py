"""Cheap pre-slice geometry checks (trimesh).

Runs before the (slow) slice so broken or oversized parts get flagged fast.
Deliberately trimmed: manifold + bed-fit + volume only. Overhang/support advice
comes authoritatively from PrusaSlicer's own warnings (see slicer.py), so we
don't re-derive it here.
"""

import os
import re

import trimesh

DEFAULT_BED = (250.0, 210.0, 220.0)  # Prusa MK4/MK4S


def bed_from_profile(profile_path: str | None) -> tuple:
    """Read build volume from a PrusaSlicer config.ini; fall back to MK4 size."""
    if not (profile_path and os.path.exists(profile_path)):
        return DEFAULT_BED
    try:
        txt = open(profile_path).read()
        x = y = z = None
        m = re.search(r"^bed_shape\s*=\s*(.+)$", txt, re.M)
        if m:
            pts = re.findall(r"(-?\d+(?:\.\d+)?)x(-?\d+(?:\.\d+)?)", m.group(1))
            xs = [float(a) for a, _ in pts]
            ys = [float(b) for _, b in pts]
            if xs and ys:
                x, y = max(xs) - min(xs), max(ys) - min(ys)
        mz = re.search(r"^max_print_height\s*=\s*([\d.]+)", txt, re.M)
        if mz:
            z = float(mz.group(1))
        return (x or DEFAULT_BED[0], y or DEFAULT_BED[1], z or DEFAULT_BED[2])
    except Exception:  # noqa: BLE001
        return DEFAULT_BED


def analyze_stl(path: str, bed: tuple = DEFAULT_BED) -> dict:
    """Return geometry checks. Never raises — a bad STL becomes a warning, not a failure."""
    try:
        m = trimesh.load(path, force="mesh")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "warnings": [f"Couldn't analyze the mesh: {exc}"]}

    ext = [float(v) for v in m.extents]
    fits = all(ext[i] <= bed[i] for i in range(3))
    warnings = []
    watertight = bool(m.is_watertight)
    if not watertight:
        warnings.append("Mesh isn't watertight (non-manifold) — it may slice or print incorrectly.")
    if not fits:
        warnings.append(
            f"Too big for the bed: {ext[0]:.0f}×{ext[1]:.0f}×{ext[2]:.0f} mm vs "
            f"{bed[0]:.0f}×{bed[1]:.0f}×{bed[2]:.0f} mm — scale it down or split it."
        )
    return {
        "ok": True,
        "watertight": watertight,
        "bbox": [round(v, 1) for v in ext],
        "fits_bed": fits,
        "bed": [round(v, 0) for v in bed],
        "volume_cm3": round(float(m.volume) / 1000, 2) if m.is_volume else None,
        "warnings": warnings,
    }
