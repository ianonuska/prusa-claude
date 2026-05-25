#!/usr/bin/env bash
# One-command setup + launch for the Prusa + Claude design tool.
set -e
cd "$(dirname "$0")"
PORT="${PORT:-8000}"

echo "▸ Prusa + Claude design tool"

# 1. virtualenv + Python deps
if [ ! -d .venv ]; then
  echo "▸ creating virtualenv…"
  python3 -m venv .venv
fi
echo "▸ installing dependencies…"
./.venv/bin/pip install -q --upgrade pip >/dev/null 2>&1 || true
./.venv/bin/pip install -q -r requirements.txt

# 2. BOSL2 (optional — enables the threads/gears toggle)
if [ ! -d libs/BOSL2 ]; then
  echo "▸ fetching BOSL2 library…"
  mkdir -p libs
  git clone --depth 1 https://github.com/BelfrySCAD/BOSL2.git libs/BOSL2 >/dev/null 2>&1 \
    || echo "  (BOSL2 clone failed — the BOSL2 toggle will be unavailable)"
fi

# 3. prerequisite checks (warn, don't block)
command -v openscad >/dev/null 2>&1 || [ -x /opt/homebrew/bin/openscad ] \
  || echo "  ⚠ OpenSCAD not found — install it:  brew install openscad"
ls -d /Applications/PrusaSlicer.app "/Applications/Original Prusa Drivers/PrusaSlicer.app" >/dev/null 2>&1 \
  || echo "  ⚠ PrusaSlicer not found — install from prusa3d.com (slice estimates will be limited)"
[ -n "$ANTHROPIC_API_KEY" ] \
  || echo "  ⚠ ANTHROPIC_API_KEY not set — export it before generating:  export ANTHROPIC_API_KEY=sk-ant-..."

# 4. launch + open the browser
echo "▸ open  http://localhost:$PORT   (Ctrl-C to stop)"
( sleep 1.8; command -v open >/dev/null 2>&1 && open "http://localhost:$PORT" ) &
exec ./.venv/bin/uvicorn app.server:app --port "$PORT"
