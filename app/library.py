"""Saved-designs library — filesystem-backed (local v1).

Each design is a folder under designs/<id>/ holding the .scad, .stl, a preview
thumbnail, and meta.json (name, conversation, params, last stats). This turns a
throwaway session into something you return to, reprint, and keep tweaking — and
it's the accumulating asset that raw Claude can't replicate.
"""

import json
import os
import shutil
import subprocess
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
DESIGNS_DIR = os.path.join(HERE, "designs")
OPENSCAD = os.environ.get("OPENSCAD_BIN") or shutil.which("openscad") or "/opt/homebrew/bin/openscad"
_LIBS = os.path.join(os.path.dirname(HERE), "libs")
try:
    from compile import MANIFOLD_ARGS
except Exception:  # noqa: BLE001
    MANIFOLD_ARGS = []
_ENV = {**os.environ, "OPENSCADPATH": os.environ.get("OPENSCADPATH") or _LIBS}

os.makedirs(DESIGNS_DIR, exist_ok=True)


def _thumb(scad_path: str, out_png: str) -> None:
    """Fast OpenCSG preview (no --render) for the library grid. Best-effort."""
    try:
        subprocess.run(
            [OPENSCAD, *MANIFOLD_ARGS, "-o", out_png, "--imgsize=320,260", "--viewall", "--autocenter",
             "--colorscheme=Tomorrow", scad_path],
            capture_output=True, env=_ENV, timeout=60,
        )
    except Exception:  # noqa: BLE001
        pass


def save_design(name: str, state: dict, scad_path: str, stl_path: str) -> dict:
    """Snapshot the current design + session into a new library entry."""
    did = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    d = os.path.join(DESIGNS_DIR, did)
    os.makedirs(d, exist_ok=True)
    if os.path.exists(scad_path):
        shutil.copy(scad_path, os.path.join(d, "design.scad"))
    if os.path.exists(stl_path):
        shutil.copy(stl_path, os.path.join(d, "design.stl"))
    _thumb(os.path.join(d, "design.scad"), os.path.join(d, "thumb.png"))

    stats = state.get("stats") or {}
    meta = {
        "id": did,
        "name": name.strip() or "untitled",
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
        "summary": (state.get("messages") and _last_summary(state)) or "",
        "print_time": stats.get("print_time"),
        "filament_g": stats.get("filament_g"),
        "params": state.get("params", []),
        "param_values": state.get("param_values", {}),
        "messages": state.get("messages", []),
        "stats": stats,
        "analysis": state.get("analysis"),
    }
    with open(os.path.join(d, "meta.json"), "w") as fh:
        json.dump(meta, fh)
    return _card(meta)


def _last_summary(state: dict) -> str:
    # best-effort: pull the most recent assistant 'summary' from stored JSON turns
    for m in reversed(state.get("messages", [])):
        if m.get("role") == "assistant":
            try:
                return (json.loads(m["content"]).get("summary") or "")[:140]
            except Exception:  # noqa: BLE001
                return ""
    return ""


def _card(meta: dict) -> dict:
    """Light view for the grid (no conversation)."""
    return {k: meta.get(k) for k in
            ("id", "name", "created_at", "summary", "print_time", "filament_g")}


def list_designs() -> list:
    cards = []
    for did in os.listdir(DESIGNS_DIR):
        mp = os.path.join(DESIGNS_DIR, did, "meta.json")
        if os.path.exists(mp):
            try:
                cards.append(_card(json.load(open(mp))))
            except Exception:  # noqa: BLE001
                continue
    return sorted(cards, key=lambda c: c["id"], reverse=True)


def load_design(did: str, scad_path: str, stl_path: str) -> dict | None:
    """Restore a saved design's files into the working slot; return its full meta."""
    d = os.path.join(DESIGNS_DIR, did)
    mp = os.path.join(d, "meta.json")
    if not os.path.exists(mp):
        return None
    meta = json.load(open(mp))
    if os.path.exists(os.path.join(d, "design.scad")):
        shutil.copy(os.path.join(d, "design.scad"), scad_path)
    if os.path.exists(os.path.join(d, "design.stl")):
        shutil.copy(os.path.join(d, "design.stl"), stl_path)
    return meta


def thumb_path(did: str) -> str | None:
    p = os.path.join(DESIGNS_DIR, did, "thumb.png")
    return p if os.path.exists(p) else None


def delete_design(did: str) -> bool:
    d = os.path.join(DESIGNS_DIR, did)
    if os.path.isdir(d) and os.path.abspath(d).startswith(os.path.abspath(DESIGNS_DIR)):
        shutil.rmtree(d)
        return True
    return False
