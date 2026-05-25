"""Interactive design loop — you drive, you judge.

Type what you want. It generates OpenSCAD, compiles it, renders a preview, and
opens the image. You look at it and decide if it's right. If not, type a
refinement ("make the base 10mm wider", "the holes should be 58mm apart") and
it regenerates with full conversation context. Nothing here scores validity —
that's your call.

Usage:
    python design.py                          # prompts you for the first ask
    python design.py "a D-shaft knob, 25mm dia, 18mm tall, 6mm shaft"
    python design.py --think                  # adaptive thinking on (slower, more careful)
    python design.py --model claude-sonnet-4-6

Commands at the refine prompt:
    <text>   refine the current design
    retry    regenerate the last ask unchanged
    open     re-open the preview images
    code     print the current .scad
    q        quit
"""

import argparse
import os
import subprocess
import sys
import time

import anthropic

from compile import compile_stl, render_previews, openscad_version
from generate import _call_claude, _extract_code, Usage


def _open(paths: list[str]) -> None:
    for p in paths:
        subprocess.run(["open", p], capture_output=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ask", nargs="*", help="initial description")
    ap.add_argument("--model", default="claude-opus-4-7")
    ap.add_argument("--think", action="store_true", help="adaptive thinking (slower, more careful)")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--out", default="out/interactive")
    ap.add_argument("--auto-fix", type=int, default=1,
                    help="silently retry this many times on a *compile* error")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    client = anthropic.Anthropic()
    messages: list[dict] = []
    session_usage = Usage()
    turn = 0

    print(f"model={args.model}  thinking={'adaptive/' + args.effort if args.think else 'off'}")
    print(f"openscad: {openscad_version()}")
    print("type your first ask (or 'q' to quit)\n")

    pending = " ".join(args.ask).strip()
    last_pngs: list[str] = []
    scad_path = os.path.join(args.out, "design.scad")
    stl_path = os.path.join(args.out, "design.stl")

    while True:
        if not pending:
            try:
                pending = input("ask> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
        if pending.lower() in ("q", "quit", "exit"):
            break
        if pending.lower() == "open":
            _open(last_pngs); pending = ""; continue
        if pending.lower() == "code":
            if os.path.exists(scad_path):
                print("\n" + open(scad_path).read() + "\n")
            pending = ""; continue

        if pending.lower() == "retry":
            if not messages:
                pending = ""; continue
            # drop the last assistant turn so we re-ask the same thing
            if messages and messages[-1]["role"] == "assistant":
                messages.pop()
        else:
            messages.append({"role": "user", "content": pending})

        turn += 1
        started = time.monotonic()
        turn_usage = Usage()
        ok = False
        warnings: list[str] = []
        err = None

        for attempt in range(args.auto_fix + 1):
            try:
                code_text, u = _call_claude(client, args.model, messages,
                                            args.effort, args.think, args.max_tokens)
            except anthropic.APIError as exc:
                err = f"API error: {exc}"
                break
            turn_usage.add(u); session_usage.add(u)
            code = _extract_code(code_text)
            with open(scad_path, "w") as fh:
                fh.write(code)
            comp = compile_stl(scad_path, stl_path)
            warnings = comp.warnings
            if comp.ok:
                ok = True
                messages.append({"role": "assistant", "content": code_text})
                break
            err = comp.stderr.strip()
            if attempt < args.auto_fix:
                # mechanical compile fix — not a validity judgment, do it silently
                messages.append({"role": "assistant", "content": code_text})
                messages.append({"role": "user", "content":
                    "That failed to compile. Fix the specific error and return the "
                    f"complete corrected program (code only).\n\nError:\n{err[:4000]}"})
            else:
                # leave the failed exchange in context so a refinement can build on it
                messages.append({"role": "assistant", "content": code_text})

        dt = time.monotonic() - started
        print(f"  [{dt:4.1f}s  ${turn_usage.cost(args.model):.3f}  "
              f"session ${session_usage.cost(args.model):.3f}]")

        if ok:
            last_pngs = render_previews(scad_path, args.out, "design")
            print(f"  scad: {scad_path}")
            print(f"  stl:  {stl_path}")
            if last_pngs:
                _open(last_pngs)
                print(f"  preview: {', '.join(os.path.basename(p) for p in last_pngs)}")
            else:
                print("  (preview render produced no image — open the STL in a viewer)")
            for w in warnings:
                print(f"  warn: {w}")
        else:
            print(f"  did not compile: {(err or '')[:300]}")
            print("  (type a refinement to steer it, or 'retry')")

        pending = ""

    print(f"\nsession total: ${session_usage.cost(args.model):.3f} over {turn} generation(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
