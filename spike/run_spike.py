"""Validation harness: run representative specs and report the numbers that
decide whether the generation thesis holds — reliability, latency, retries,
and cost per generation.

Usage:
    python run_spike.py                         # all sample specs, opus-4-7
    python run_spike.py --model claude-sonnet-4-6
    python run_spike.py phone_stand_iphone15pro pi5_wall_bracket
    python run_spike.py --no-thinking --effort medium
"""

import argparse
import sys

import anthropic

from categories import SAMPLE_SPECS
from compile import openscad_version
from generate import generate
from prompts import PROMPT_VERSION


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec_ids", nargs="*", help="subset of spec ids to run")
    ap.add_argument("--model", default="claude-opus-4-7")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--no-thinking", action="store_true")
    ap.add_argument("--max-repairs", type=int, default=2)
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    specs = SAMPLE_SPECS
    if args.spec_ids:
        wanted = set(args.spec_ids)
        specs = [s for s in SAMPLE_SPECS if s["id"] in wanted]
        missing = wanted - {s["id"] for s in specs}
        if missing:
            print(f"unknown spec ids: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    print(f"prompt={PROMPT_VERSION}  model={args.model}  "
          f"thinking={'off' if args.no_thinking else f'adaptive/{args.effort}'}")
    print(f"openscad: {openscad_version()}")
    print(f"running {len(specs)} spec(s)\n")

    client = anthropic.Anthropic()
    results = []
    for spec in specs:
        print(f"  -> {spec['id']} ...", flush=True)
        res = generate(
            spec, client=client, model=args.model, out_dir=args.out,
            max_repairs=args.max_repairs, effort=args.effort,
            thinking=not args.no_thinking, render=not args.no_render,
        )
        results.append(res)
        status = "OK " if res.ok else "FAIL"
        print(f"     {status} attempts={res.attempts} {res.latency_s:5.1f}s "
              f"${res.cost_usd:.3f} cache_read={res.usage.cache_read}")
        for w in res.warnings:
            print(f"       warn: {w}")
        if res.error:
            print(f"       error: {res.error[:200]}")

    ok = sum(1 for r in results if r.ok)
    first_try = sum(1 for r in results if r.ok and r.attempts == 1)
    total_cost = sum(r.cost_usd for r in results)
    avg_lat = sum(r.latency_s for r in results) / max(len(results), 1)

    print("\n" + "=" * 60)
    print(f"reliability:   {ok}/{len(results)} compiled   "
          f"({first_try}/{len(results)} on first try)")
    print(f"avg latency:   {avg_lat:.1f}s")
    print(f"total cost:    ${total_cost:.3f}   (avg ${total_cost/max(len(results),1):.3f}/gen)")
    print("artifacts in:  " + args.out + "/<spec_id>/")
    print("=" * 60)
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
