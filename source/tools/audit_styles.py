#!/usr/bin/env python3
"""Audit style values used by themes.json against the engine's explicit supported-value registry."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
THEMES = ROOT / "source" / "render" / "themes.json"
SUPPORTED = {
    "pattern": ['arabesque', 'arcs', 'aurora', 'bokeh', 'burst', 'deco', 'dots', 'grid', 'scan', 'stripes', 'topo', 'waves', 'none', 'grain', 'orbit', 'rings', 'diagonal', 'crosshatch', 'contour', 'paper', 'halftone', 'wave', 'topographic', 'starfield', 'checker', 'woven', 'ripple', 'facets', 'radial', 'mesh', 'tile', 'crystal', 'wash', 'metal', 'stars', 'confetti', 'blobs', 'rain', 'engrave', 'spray', 'enso', 'sunsetgrid'],
    "frame": ['arch', 'bar', 'brackets', 'deco', 'double', 'neon', 'none', 'ornate', 'plain', 'round', 'ticket', 'line', 'thin', 'editorial', 'rounded', 'technical', 'corner'],
    "orn": ['circle', 'diamond', 'drop', 'hex', 'leaf', 'moon', 'plus', 'spark', 'square', 'sun', 'tri', 'star', 'dot', 'wave', 'none'],
    "chip": ['glass', 'outline', 'block', 'tag', 'pill', 'solid', 'paper', 'none'],
    "rule": ['bar', 'dots', 'line', 'orn', 'double', 'none', 'dot'],
    "rays": ['none', 'sunburst', 'conic', 'rings', 'beam', 'orbit', 'subtle', 'radial'],
    "particles": ['spark', 'ember', 'snow', 'bubble', 'square', 'dot', 'none', 'dust', 'star', 'confetti', 'leaf', 'drop', 'diamond'],
    "arch": ['arch', 'hex', 'oval', 'circle', 'rect', 'diamond', 'none', 'rounded', 'cut', 'angled', 'burst'],
    "motion": ['smooth', 'snappy', 'float', 'kinetic', 'parallax', 'stagger', 'pulse', 'rise', 'snap', 'drift', 'orbit', 'reveal', 'slow'],
}
SITE = ROOT / "source" / "render" / "site"
SRC = {n: (SITE / n).read_text(encoding="utf-8") for n in ("decor.js", "base.js", "scenes.js", "style.css")}
# Where each field's drawing code lives.
FIELD_FILES = {
    "pattern": ["decor.js"], "frame": ["decor.js"], "orn": ["base.js"], "chip": ["style.css", "scenes.js"],
    "rule": ["scenes.js"], "rays": ["scenes.js"], "particles": ["decor.js"], "arch": ["scenes.js"], "motion": ["base.js"],
}
# Values that are legitimately handled by a default/else branch or intentionally draw nothing.
# Every entry here is a deliberate decision; anything else must appear literally in the source.
FALLBACK = {
    "pattern": {"none"}, "frame": {"none"}, "orn": {"none", "star"}, "chip": {"pill"},
    "rule": {"orn"}, "rays": {"sunburst", "conic"}, "particles": {"none", "dot"},
    "arch": {"none", "arch"}, "motion": {"smooth"},
}
def literal_in_source(field, value):
    pats = ['"%s"' % value, "'%s'" % value, 'data-chip="%s"' % value]
    return any(pt in SRC[f] for f in FIELD_FILES[field] for pt in pats)
code_gaps = []
for field, allowed in SUPPORTED.items():
    for v in allowed:
        if v in FALLBACK.get(field, set()):
            continue
        if not literal_in_source(field, v):
            code_gaps.append(f"{field}={v}")
if code_gaps:
    raise SystemExit("ERROR: registry values with no literal drawing branch in source: " + ", ".join(code_gaps))
print("Source check: every non-fallback registry value appears in its drawing code.")

data = json.loads(THEMES.read_text(encoding="utf-8"))
themes = data["themes"]
failed = False
print(f"থিম সংখ্যা: {len(themes)}")
for field, allowed in SUPPORTED.items():
    used = sorted({str(t.get("style", {}).get(field, "(missing)")) for t in themes.values()})
    gaps = [v for v in used if v not in allowed]
    print(f"\n{field}: ব্যবহৃত {len(used)}টি value")
    print("  ব্যবহৃত:", ", ".join(used))
    print("  drawing code নেই:", ", ".join(gaps) if gaps else "কোনো gap নেই")
    if gaps:
        failed = True
if failed:
    raise SystemExit("ERROR: অজানা style value পাওয়া গেছে")
print("\nPASS: সব theme style value supported registry-তে আছে (0 gaps).")
