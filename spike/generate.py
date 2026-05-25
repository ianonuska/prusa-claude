"""Generation core: spec -> Claude -> OpenSCAD -> STL + preview, with repair.

This is the load-bearing thesis: given a precise guided spec, can Claude
reliably produce a printable parametric model, fast enough to matter? Everything
here is instrumented (latency, attempts, token cost, manifold warnings) so we
can answer that with numbers instead of vibes.
"""

import os
import re
import time
from dataclasses import dataclass, field

import anthropic

from prompts import OPENSCAD_SYSTEM_PROMPT, PROMPT_VERSION, render_spec
from compile import compile_stl, render_previews

# Pricing per 1M tokens (input, output). Cache write = 1.25x input, read = 0.1x.
PRICING = {
    "claude-opus-4-7":   (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5":  (1.0, 5.0),
}

_FENCE_RE = re.compile(r"```(?:openscad|scad|c)?\s*(.*?)```", re.DOTALL)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation: int = 0
    cache_read: int = 0

    def add(self, u) -> None:
        self.input_tokens += getattr(u, "input_tokens", 0) or 0
        self.output_tokens += getattr(u, "output_tokens", 0) or 0
        self.cache_creation += getattr(u, "cache_creation_input_tokens", 0) or 0
        self.cache_read += getattr(u, "cache_read_input_tokens", 0) or 0

    def cost(self, model: str) -> float:
        cin, cout = PRICING.get(model, (5.0, 25.0))
        return (
            self.input_tokens * cin
            + self.output_tokens * cout
            + self.cache_creation * cin * 1.25
            + self.cache_read * cin * 0.1
        ) / 1_000_000


@dataclass
class GenResult:
    spec_id: str
    model: str
    ok: bool
    attempts: int
    latency_s: float
    usage: Usage
    cost_usd: float
    scad_path: str | None = None
    stl_path: str | None = None
    png_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def _extract_code(text: str) -> str:
    """Pull OpenSCAD out of the response, tolerating stray fences/prose."""
    text = text.strip()
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text


def _system_blocks():
    """System prompt as a cacheable block. Caches automatically once the prompt
    crosses the model's minimum prefix (4096 tok on Opus 4.7)."""
    return [{
        "type": "text",
        "text": OPENSCAD_SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }]


def _call_claude(client, model, messages, effort, thinking, max_tokens):
    """One streamed Messages call. Returns (text, usage)."""
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=_system_blocks(),
        messages=messages,
    )
    if thinking:
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": effort}
    with client.messages.stream(**kwargs) as stream:
        final = stream.get_final_message()
    text = "".join(b.text for b in final.content if b.type == "text")
    return text, final.usage


def generate(spec: dict, client=None, model: str = "claude-opus-4-7",
            out_dir: str = "out", max_repairs: int = 2, effort: str = "high",
            thinking: bool = True, max_tokens: int = 16000,
            render: bool = True) -> GenResult:
    """Run one spec end to end, repairing compile errors up to max_repairs times."""
    client = client or anthropic.Anthropic()
    spec_id = spec["id"]
    work = os.path.join(out_dir, spec_id)
    os.makedirs(work, exist_ok=True)

    usage = Usage()
    messages = [{"role": "user", "content": render_spec(spec)}]
    started = time.monotonic()
    last_err = None
    code = ""

    for attempt in range(1, max_repairs + 2):
        try:
            code_text, u = _call_claude(client, model, messages, effort, thinking, max_tokens)
        except anthropic.APIError as exc:
            return GenResult(spec_id, model, False, attempt,
                             time.monotonic() - started, usage,
                             usage.cost(model), error=f"API error: {exc}")
        usage.add(u)
        code = _extract_code(code_text)

        scad_path = os.path.join(work, f"{spec_id}.scad")
        with open(scad_path, "w") as fh:
            fh.write(code)

        stl_path = os.path.join(work, f"{spec_id}.stl")
        comp = compile_stl(scad_path, stl_path)

        if comp.ok:
            pngs = render_previews(scad_path, work, spec_id) if render else []
            return GenResult(
                spec_id, model, True, attempt, time.monotonic() - started,
                usage, usage.cost(model), scad_path=scad_path, stl_path=stl_path,
                png_paths=pngs, warnings=comp.warnings,
            )

        # Compile failed — feed the exact error back and try again.
        last_err = comp.stderr.strip()
        messages.append({"role": "assistant", "content": code_text})
        messages.append({"role": "user", "content":
            "That OpenSCAD code failed to compile. Fix the specific problem and "
            "return the complete corrected program (code only).\n\n"
            f"OpenSCAD error output:\n{last_err[:4000]}"})

    return GenResult(
        spec_id, model, False, max_repairs + 1, time.monotonic() - started,
        usage, usage.cost(model),
        scad_path=os.path.join(work, f"{spec_id}.scad"),
        error=last_err or "failed to compile after retries",
    )
