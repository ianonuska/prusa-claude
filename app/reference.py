"""Reference-dimension library — inject known real-world sizes so Claude uses
exact measurements instead of hallucinating them.

When the user's text mentions a known object (a phone, an M3 screw, a Pi), the
matching dimensions are prepended to that turn. This is the cheapest, highest-
leverage accuracy win: the system supplies the number, the model doesn't guess.
"""

import re

# key -> (label, dimension string). Dims are bare/nominal; the model applies the
# clearance rules on top.
REFERENCE = {
    # --- phones (H x W x D, bare device) ---
    "iphone15pro": ("iPhone 15 Pro", "146.6 × 70.6 × 8.25 mm (bare; add ~1.5–2 mm/side for a case)"),
    "iphone15": ("iPhone 15", "147.6 × 71.6 × 7.80 mm (bare; add case allowance)"),
    "iphone14pro": ("iPhone 14 Pro", "147.5 × 71.5 × 7.85 mm (bare)"),
    "pixel8": ("Pixel 8", "150.5 × 70.8 × 8.9 mm (bare)"),
    "galaxys24": ("Samsung Galaxy S24", "147.0 × 70.6 × 7.6 mm (bare)"),
    # --- metric fasteners ---
    "m2": ("M2 screw", "clearance hole 2.4 mm, self-tap 1.6 mm, socket head Ø3.8 mm, nut 4.0 mm AF"),
    "m2.5": ("M2.5 screw", "clearance hole 2.9 mm, self-tap 2.05 mm, socket head Ø4.5 mm, nut 5.0 mm AF"),
    "m3": ("M3 screw", "clearance hole 3.4 mm, self-tap-into-plastic 2.5 mm, socket head Ø5.5 mm, nut 5.5 mm AF, heat-set insert hole ~4.0 mm"),
    "m4": ("M4 screw", "clearance hole 4.5 mm, self-tap 3.3 mm, socket head Ø7.0 mm, nut 7.0 mm AF, heat-set insert hole ~5.6 mm"),
    "m5": ("M5 screw", "clearance hole 5.5 mm, self-tap 4.2 mm, socket head Ø8.5 mm, nut 8.0 mm AF, heat-set insert hole ~6.4 mm"),
    "m6": ("M6 screw", "clearance hole 6.6 mm, self-tap 5.0 mm, socket head Ø10.0 mm, nut 10.0 mm AF"),
    # --- single-board computers ---
    "rpi5": ("Raspberry Pi 5 / 4B", "board 85 × 56 mm; 4 mounting holes Ø2.7 mm on a 58 × 49 mm rectangle, 3.5 mm from the edges"),
    "rpizero": ("Raspberry Pi Zero 2 W", "board 65 × 30 mm; 4 holes Ø2.75 mm on a 58 × 23 mm rectangle"),
    "arduinouno": ("Arduino Uno R3", "board 68.6 × 53.4 mm; holes Ø3.2 mm (irregular pattern)"),
    "esp32": ("ESP32 DevKit V1", "≈ 51.5 × 28.3 mm (varies by board — confirm yours)"),
    # --- bearings (ID x OD x width) ---
    "608": ("608 bearing", "8 × 22 × 7 mm (ID × OD × W)"),
    "623": ("623 bearing", "3 × 10 × 4 mm"),
    "625": ("625 bearing", "5 × 16 × 5 mm"),
    "6800": ("6800 bearing", "10 × 19 × 5 mm"),
    # --- batteries (Ø x L, or W x L x T) ---
    "18650": ("18650 cell", "18.6 × 65.2 mm (Ø × L)"),
    "aa": ("AA battery", "14.5 × 50.5 mm (Ø × L)"),
    "aaa": ("AAA battery", "10.5 × 44.5 mm (Ø × L)"),
    "9v": ("9V battery", "26.5 × 17.5 × 48.5 mm"),
    # --- misc ---
    "usbc": ("USB-C receptacle", "cutout ≈ 9.0 × 3.2 mm"),
    "creditcard": ("Credit / ID card", "85.6 × 53.98 × 0.76 mm"),
}

# regex patterns per key (word-boundaried so 'm3' doesn't match 'm30')
_ALIASES = {
    "iphone15pro": [r"iphone\s*15\s*pro"],
    "iphone15": [r"iphone\s*15(?!\s*pro)"],
    "iphone14pro": [r"iphone\s*14\s*pro"],
    "pixel8": [r"pixel\s*8"],
    "galaxys24": [r"galaxy\s*s\s*24", r"\bs24\b"],
    "m2": [r"\bm2\b"],
    "m2.5": [r"\bm2\.5\b"],
    "m3": [r"\bm3\b"],
    "m4": [r"\bm4\b"],
    "m5": [r"\bm5\b"],
    "m6": [r"\bm6\b"],
    "rpi5": [r"raspberry\s*pi\s*[45]", r"\brpi\s*[45]\b", r"\bpi\s*[45]\b"],
    "rpizero": [r"pi\s*zero", r"raspberry\s*pi\s*zero"],
    "arduinouno": [r"arduino\s*uno", r"\buno\b"],
    "esp32": [r"esp\s*32"],
    "608": [r"\b608\b"],
    "623": [r"\b623\b"],
    "625": [r"\b625\b"],
    "6800": [r"\b6800\b"],
    "18650": [r"\b18650\b"],
    "aa": [r"\baa\b", r"\baa\s*batter"],
    "aaa": [r"\baaa\b"],
    "9v": [r"\b9\s*v\b", r"9\s*volt"],
    "usbc": [r"usb[\s-]*c", r"type[\s-]*c"],
    "creditcard": [r"credit\s*card", r"\bid\s*card\b"],
}


def hints(text: str):
    """Return (injected_block, [matched labels]) for any known objects in the text."""
    matched = []
    for key, pats in _ALIASES.items():
        if any(re.search(p, text, re.I) for p in pats):
            matched.append(key)
    if not matched:
        return "", []
    lines = [f"- {REFERENCE[k][0]}: {REFERENCE[k][1]}" for k in matched]
    block = ("Known real-world dimensions (use these EXACTLY; apply the clearance rules on top):\n"
             + "\n".join(lines) + "\n\n")
    return block, [REFERENCE[k][0] for k in matched]
