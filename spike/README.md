# Generation spike

Throwaway CLI to answer one question before we build any UI: **given a precise
guided spec, can Claude reliably produce a printable parametric OpenSCAD model,
fast and cheap enough to matter?**

No web app, no DB, no auth — just `spec -> Claude -> OpenSCAD -> STL + preview`,
instrumented for reliability, latency, retries, and cost.

## Layout

- `prompts.py` — the OpenSCAD system prompt (the product IP) + spec renderer
- `categories.py` — guided-interview definitions + completed sample specs
- `compile.py` — headless OpenSCAD: `.scad -> .stl` and preview PNGs
- `generate.py` — the core: Claude call (cached system prompt, adaptive
  thinking), code extraction, compile, auto-repair loop, cost accounting
- `run_spike.py` — runs sample specs and prints the scoreboard
- `out/<spec_id>/` — generated `.scad`, `.stl`, preview `.png`s

## Run

```bash
cd <repo-root>                     # the project directory
source .venv/bin/activate          # created by ../run.sh
export ANTHROPIC_API_KEY=sk-ant-...

cd spike
python run_spike.py                                  # all specs, opus-4-7
python run_spike.py --model claude-sonnet-4-6        # production-cost model
python run_spike.py phone_stand_iphone15pro          # one spec
python run_spike.py --no-thinking --effort medium    # latency/quality knobs
```

## What to look at

- **reliability** — did it compile, and on the first try?
- **latency** — this is the number in tension with the 60-second booth demo.
- **cost/gen** — at $10/mo unlimited, this sets the margin. Compare opus vs
  sonnet.
- **the STL/PNGs** — open them. "Compiled" is necessary, not sufficient; the
  real test is whether the part is actually printable and correct.
