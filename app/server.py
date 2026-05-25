"""Local web app backend — wraps the describe -> see -> slice loop, and guides
the user with clickable questions/suggestions like Claude does.

Single in-memory session (v0 = one user). Reuses the spike OpenSCAD rules and
compile step; adds structured output so every turn returns code + guidance.

Run from the repo root:
    ./.venv/bin/uvicorn app.server:app --reload --port 8000
then open http://localhost:8000
"""

import json
import os
import shutil
import sys
import time

import anthropic
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)                           # so `import slicer` resolves
sys.path.insert(0, os.path.join(ROOT, "spike"))   # reuse the OpenSCAD rules

from prompts import APP_SYSTEM_PROMPT, APP_SYSTEM_PROMPT_BOSL2  # noqa: E402
from compile import compile_stl  # noqa: E402
from generate import Usage, _extract_code  # noqa: E402
import slicer  # noqa: E402
import customizer  # noqa: E402
import library  # noqa: E402
import reference  # noqa: E402
from analysis import analyze_stl, bed_from_profile  # noqa: E402

MODEL = os.environ.get("PRUSA_MODEL", "claude-opus-4-7")
BUNDLED_PROFILE = os.path.join(HERE, "profiles", "mk4s_pla.ini")  # generic MK4S+PLA default
DEFAULT_PROFILE = os.environ.get("PRUSA_PROFILE") or BUNDLED_PROFILE
WORK = os.path.join(HERE, "work")
os.makedirs(WORK, exist_ok=True)
SCAD = os.path.join(WORK, "design.scad")
STL = os.path.join(WORK, "design.stl")

# Structured-output schema: code to print + guidance to click.
RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "code": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["prompt", "options"],
                "additionalProperties": False,
            },
        },
        "suggestions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "code", "questions", "suggestions"],
    "additionalProperties": False,
}

client = anthropic.Anthropic()
app = FastAPI()

STATE: dict = {
    "messages": [], "turn": 0, "stats": None, "analysis": None, "usage": Usage(),
    "params": [], "param_values": {},
    "profile": DEFAULT_PROFILE,
    "profile_name": os.path.basename(DEFAULT_PROFILE) + (" (bundled default)"
                    if DEFAULT_PROFILE == BUNDLED_PROFILE else ""),
}


class ChatIn(BaseModel):
    text: str
    careful: bool = False
    bosl2: bool = False  # opt-in: inject BOSL2 awareness (threads/gears/screws)


class ProfileIn(BaseModel):
    name: str
    content: str


class ParamsIn(BaseModel):
    values: dict


class SaveIn(BaseModel):
    name: str


class IdIn(BaseModel):
    id: str


def _system_blocks(bosl2: bool = False):
    text = APP_SYSTEM_PROMPT_BOSL2 if bosl2 else APP_SYSTEM_PROMPT
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _call(messages, careful, bosl2=False):
    """One structured generation call. Returns (data_dict, raw_text, usage)."""
    output_config = {"format": {"type": "json_schema", "schema": RESULT_SCHEMA}}
    kwargs = dict(model=MODEL, max_tokens=16000, system=_system_blocks(bosl2),
                  messages=messages, output_config=output_config)
    if careful:
        kwargs["thinking"] = {"type": "adaptive"}
        output_config["effort"] = "high"
    with client.messages.stream(**kwargs) as stream:
        final = stream.get_final_message()
    raw = "".join(b.text for b in final.content if b.type == "text")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # schema should prevent this; degrade gracefully to code-only
        data = {"summary": "", "code": _extract_code(raw), "questions": [], "suggestions": []}
    return data, raw, final.usage


def _stats_preamble() -> str:
    bits = []
    if STATE["stats"]:
        bits.append("slices to " + slicer.stats_summary(STATE["stats"]))
    a = STATE.get("analysis")
    if a and a.get("warnings"):
        bits.append("geometry flags: " + "; ".join(a["warnings"]))
    if not bits:
        return ""
    return ("The current design " + ". ".join(bits) + ".\n"
            "Account for that if the request is about size, print time, material, strength, or supports.\n\n")


@app.post("/api/chat")
def chat(inp: ChatIn):
    messages = STATE["messages"]
    ref_block, ref_names = reference.hints(inp.text)  # inject known real-world dimensions
    messages.append({"role": "user", "content": _stats_preamble() + ref_block + inp.text})

    started = time.monotonic()
    turn_usage = Usage()
    err = None
    ok = False
    data: dict = {}
    comp = None

    for attempt in range(2):  # one silent auto-fix for compile errors
        try:
            data, raw, u = _call(messages, inp.careful, inp.bosl2)
        except anthropic.APIError as exc:
            err = f"API error: {exc}"
            break
        turn_usage.add(u)
        STATE["usage"].add(u)
        with open(SCAD, "w") as fh:
            fh.write(data.get("code", ""))
        comp = compile_stl(SCAD, STL)
        messages.append({"role": "assistant", "content": raw})
        if comp.ok:
            ok = True
            break
        err = comp.stderr.strip()
        if attempt == 0:
            if "Can't open include file" in err or "Ignoring unknown" in err:
                fix = ("A library include failed (BOSL2 may be unavailable). Rewrite the part "
                       "using ONLY built-in OpenSCAD primitives — no include/use statements — "
                       "and return the full JSON.\n\nError:\n" + err[:2000])
            else:
                fix = ("That OpenSCAD failed to compile. Fix the specific error and return the "
                       "full JSON again with corrected code.\n\nError:\n" + err[:4000])
            messages.append({"role": "user", "content": fix})

    resp: dict = {
        "ok": ok,
        "latency_s": round(time.monotonic() - started, 1),
        "turn_cost": round(turn_usage.cost(MODEL), 4),
        "session_cost": round(STATE["usage"].cost(MODEL), 4),
        "summary": data.get("summary", ""),
        "questions": data.get("questions", []),
        "suggestions": data.get("suggestions", []),
        "warnings": comp.warnings if (ok and comp) else [],
        "references_used": ref_names,
        "error": None if ok else (err or "generation failed"),
    }
    if ok:
        STATE["turn"] += 1
        params = customizer.parse_params(data.get("code", ""))
        STATE["params"] = params
        STATE["param_values"] = {p["name"]: p["value"] for p in params}
        analysis = analyze_stl(STL, bed=bed_from_profile(STATE["profile"]))  # cheap pre-slice checks
        STATE["analysis"] = analysis
        stats = slicer.slice_stats(STL, profile_path=STATE["profile"])
        STATE["stats"] = stats if stats.get("ok") else None
        resp["stats"] = stats
        resp["analysis"] = analysis
        resp["params"] = params
        resp["parts"] = customizer.detect_parts(params)
        resp["stl_url"] = f"/api/stl?v={STATE['turn']}"
        resp["turn"] = STATE["turn"]
    return JSONResponse(resp)


@app.get("/api/stl")
def get_stl(v: int = 0):
    if not os.path.exists(STL):
        return JSONResponse({"error": "no model yet"}, status_code=404)
    return FileResponse(STL, media_type="model/stl", filename="design.stl")


@app.get("/api/scad")
def get_scad():
    if not os.path.exists(SCAD):
        return JSONResponse({"error": "no code yet"}, status_code=404)
    return FileResponse(SCAD, media_type="text/plain", filename="design.scad")


@app.post("/api/open-slicer")
def open_slicer():
    if not os.path.exists(STL):
        return JSONResponse({"ok": False, "error": "no model yet"}, status_code=404)
    return JSONResponse(slicer.open_in_slicer(STL, profile_path=STATE["profile"]))


@app.post("/api/reset")
def reset():
    STATE.update({"messages": [], "turn": 0, "stats": None, "analysis": None,
                  "params": [], "param_values": {}, "usage": Usage()})
    return JSONResponse({"ok": True})


@app.post("/api/set-profile")
def set_profile(p: ProfileIn):
    """Accept an exported PrusaSlicer config.ini (as text) for real per-printer numbers."""
    path = os.path.join(WORK, "user_profile.ini")
    with open(path, "w") as fh:
        fh.write(p.content)
    STATE["profile"] = path
    STATE["profile_name"] = p.name
    return JSONResponse({"ok": True, "profile": p.name})


@app.post("/api/set-params")
def set_params(inp: ParamsIn):
    """Re-render the current design with slider-overridden values (no Claude call)."""
    if not os.path.exists(SCAD):
        return JSONResponse({"ok": False, "error": "no design yet"}, status_code=400)
    STATE["param_values"].update(inp.values)
    ok, err = customizer.render_with_params(SCAD, STATE["param_values"], STL)
    if not ok:
        return JSONResponse({"ok": False, "error": err})
    STATE["turn"] += 1
    analysis = analyze_stl(STL, bed=bed_from_profile(STATE["profile"]))
    STATE["analysis"] = analysis
    stats = slicer.slice_stats(STL, profile_path=STATE["profile"])
    STATE["stats"] = stats if stats.get("ok") else None
    return JSONResponse({"ok": True, "turn": STATE["turn"],
                         "stl_url": f"/api/stl?v={STATE['turn']}",
                         "stats": stats, "analysis": analysis})


@app.post("/api/save")
def save(inp: SaveIn):
    if not os.path.exists(SCAD):
        return JSONResponse({"ok": False, "error": "no design to save yet"}, status_code=400)
    return JSONResponse({"ok": True, "design": library.save_design(inp.name, STATE, SCAD, STL)})


@app.get("/api/designs")
def designs():
    return JSONResponse({"designs": library.list_designs()})


@app.get("/api/thumb/{did}")
def thumb(did: str):
    p = library.thumb_path(did)
    if not p:
        return JSONResponse({"error": "no thumbnail"}, status_code=404)
    return FileResponse(p, media_type="image/png")


@app.post("/api/load")
def load(inp: IdIn):
    meta = library.load_design(inp.id, SCAD, STL)
    if not meta:
        return JSONResponse({"ok": False, "error": "design not found"}, status_code=404)
    STATE["messages"] = meta.get("messages", [])
    # re-parse sliders from the restored .scad so tuning always works on a load
    code = open(SCAD).read() if os.path.exists(SCAD) else ""
    STATE["params"] = customizer.parse_params(code) or meta.get("params", [])
    STATE["param_values"] = {p["name"]: p["value"] for p in STATE["params"]}
    STATE["stats"] = meta.get("stats") or None
    STATE["analysis"] = meta.get("analysis")
    STATE["turn"] += 1
    return JSONResponse({
        "ok": True, "name": meta["name"], "summary": meta.get("summary", ""),
        "stl_url": f"/api/stl?v={STATE['turn']}", "params": STATE["params"],
        "parts": customizer.detect_parts(STATE["params"]),
        "stats": STATE["stats"], "analysis": STATE["analysis"],
    })


@app.post("/api/delete")
def delete(inp: IdIn):
    return JSONResponse({"ok": library.delete_design(inp.id)})


@app.get("/api/config")
def config():
    return JSONResponse({
        "model": MODEL,
        "profile": STATE["profile_name"],
        "prusa_found": os.path.exists(slicer.PRUSA_BIN),
        "openscad_found": bool(shutil.which("openscad") or os.path.exists(customizer.OPENSCAD)),
        "bosl2_found": os.path.isdir(os.path.join(ROOT, "libs", "BOSL2")),
        "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
    })


app.mount("/", StaticFiles(directory=os.path.join(HERE, "static"), html=True), name="static")
