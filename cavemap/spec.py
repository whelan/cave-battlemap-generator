"""Read and normalise a ```cave fence (see ../spec-reference.md).

Coordinates are in grid cells (1 cell = 5 ft), origin top-left, x right, y down.
"""
import math
import re
from pathlib import Path

import yaml

EDGES = ("north", "south", "east", "west")

GLOW_COLOURS = {
    "amber": (255, 186, 84),
    "teal": (120, 232, 228),
    "pale-blue": (168, 212, 255),
    "violet": (196, 150, 255),
    "sickly-green": (176, 232, 120),
    "red": (255, 96, 80),
}
LIGHT_COLOURS = {
    "fire": (255, 170, 80),
    "torch": (255, 160, 70),
    "candle": (255, 200, 120),
    "moon": (170, 196, 255),
    "lava": (255, 112, 40),
    **GLOW_COLOURS,
}
FEATURE_KINDS = ("camp", "fire", "bedroll", "pack", "bones", "blood", "crate", "altar", "carcass",
                 "nest", "cage", "corpse", "statue", "treasure", "torch", "moonbeam", "claws", "tracks",
                 "web", "roots", "stalagmite", "moss", "skull", "spear", "chains",
                 "brazier", "scorch", "trap", "charred")
DM_ONLY = ("trap",)  # drawn only with --labels (the preview, or a DM copy of the map)


class SpecError(Exception):
    pass


def _pt(v, where):
    if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(c, (int, float)) for c in v)):
        raise SpecError(f"{where}: expected [x, y] in cells, got {v!r}")
    return (float(v[0]), float(v[1]))


def _radii(v, where):
    if isinstance(v, (int, float)):
        return (float(v), float(v))
    return _pt(v, where)


def read_fence(note):
    text = Path(note).read_text(encoding="utf-8")
    if Path(note).suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise SpecError("the cave spec must be a YAML mapping")
        return data
    m = re.search(r"^```cave[ \t]*\n(.*?)^```", text, re.S | re.M)
    if not m:
        raise SpecError(f"{note}: no ```cave fence")
    data = yaml.safe_load(m.group(1)) or {}
    if not isinstance(data, dict):
        raise SpecError("the cave fence must be a YAML mapping")
    return data


def normalise(d):
    s = {}
    s["name"] = str(d.get("name") or "Cave")
    s["slug"] = re.sub(r"[^a-z0-9]+", "-", s["name"].lower().replace("æ", "ae").replace("ø", "oe").replace("å", "aa")).strip("-")
    W, H = _pt(d.get("size", [30, 30]), "size")
    s["W"], s["H"] = int(W), int(H)
    s["seed"] = int(d.get("seed", 1))
    s["px"] = int(d.get("px", 100))
    s["darkness"] = float(d.get("darkness", 0.6))
    s["roughness"] = float(d.get("roughness", 1.0))
    s["damp"] = float(d.get("damp", 1.0))
    s["rocks"] = int(d.get("rocks", 14))
    s["puddles"] = int(d.get("puddles", 4))
    s["stalagmites"] = int(d.get("stalagmites", 0))
    s["cracks"] = int(d.get("cracks", 3))

    s["chambers"] = []
    ids = {}
    for i, c in enumerate(d.get("chambers") or []):
        w = f"chambers[{i}]"
        ch = {"id": str(c.get("id", f"c{i}")), "at": _pt(c.get("at"), w), "r": _radii(c.get("r", 4), w),
              "rot": math.radians(float(c.get("rot", 0))), "label": c.get("label")}
        s["chambers"].append(ch)
        ids[ch["id"]] = ch["at"]
    if not s["chambers"]:
        raise SpecError("a cave needs at least one chamber")

    def resolve(p, where):
        if isinstance(p, str):
            if p in ids:
                return ids[p]
            if p in EDGES:
                return p
            raise SpecError(f"{where}: unknown chamber or edge {p!r}")
        return _pt(p, where)

    s["passages"] = []
    for i, p in enumerate(d.get("passages") or []):
        w = f"passages[{i}]"
        pts = p.get("path") or [p.get("from"), p.get("to")]
        if len(pts) < 2 or None in pts:
            raise SpecError(f"{w}: give from/to or a path of two or more points")
        pts = [resolve(q, w) for q in pts]
        # an edge keyword projects its neighbour onto that edge, then 2 cells past it
        out = []
        for j, q in enumerate(pts):
            if isinstance(q, str):
                nb = pts[j - 1] if j else pts[1]
                if isinstance(nb, str):
                    raise SpecError(f"{w}: two edges in a row")
                x, y = nb
                q = {"north": (x, -2), "south": (x, s["H"] + 2), "west": (-2, y), "east": (s["W"] + 2, y)}[q]
                s.setdefault("exits", []).append((w, q))
            out.append(q)
        s["passages"].append({"pts": out, "width": float(p.get("width", 2.5)), "where": w,
                              "secret": bool(p.get("secret", False)), "label": p.get("label")})

    s["pillars"] = [{"at": _pt(p.get("at"), f"pillars[{i}]"), "r": _radii(p.get("r", 2), f"pillars[{i}]"),
                     "rot": math.radians(float(p.get("rot", 0)))} for i, p in enumerate(d.get("pillars") or [])]
    s["pools"] = [{"at": _pt(p.get("at"), f"pools[{i}]"), "r": _radii(p.get("r", 2), f"pools[{i}]"),
                   "rot": math.radians(float(p.get("rot", 0))), "deep": bool(p.get("deep", True))}
                  for i, p in enumerate(d.get("pools") or [])]

    def ell(key):
        return [{"at": _pt(p.get("at"), f"{key}[{i}]"), "r": _radii(p.get("r", 2), f"{key}[{i}]"),
                 "rot": math.radians(float(p.get("rot", 0))), "height": float(p.get("height", 5)),
                 "label": p.get("label")}
                for i, p in enumerate(d.get(key) or [])]

    s["ledges"] = ell("ledges")
    s["chasms"] = ell("chasms")
    s["streams"] = [{"pts": [_pt(q, f"streams[{i}]") for q in p.get("path", [])], "width": float(p.get("width", 1))}
                    for i, p in enumerate(d.get("streams") or [])]
    s["stairs"] = [{"at": _pt(p.get("at"), f"stairs[{i}]"), "rot": math.radians(float(p.get("rot", 0))),
                    "w": float(p.get("w", 2)), "l": float(p.get("l", 2)), "n": int(p.get("n", 5)),
                    "down": bool(p.get("down", True))} for i, p in enumerate(d.get("stairs") or [])]
    s["lava"] = []
    for i, p in enumerate(d.get("lava") or []):
        if p.get("path"):
            s["lava"].append({"pts": [_pt(q, f"lava[{i}]") for q in p["path"]], "width": float(p.get("width", 2))})
        else:
            s["lava"].append({"at": _pt(p.get("at"), f"lava[{i}]"), "r": _radii(p.get("r", 2), f"lava[{i}]"),
                              "rot": math.radians(float(p.get("rot", 0)))})
    s["crack_paths"] = [[_pt(q, f"crack_paths[{i}]") for q in c] for i, c in enumerate(d.get("crack_paths") or [])]

    s["glow"] = []
    for i, g in enumerate(d.get("glow") or []):
        col = g.get("color", "teal")
        if col not in GLOW_COLOURS:
            raise SpecError(f"glow[{i}]: color must be one of {', '.join(GLOW_COLOURS)}")
        s["glow"].append({"at": _pt(g.get("at"), f"glow[{i}]"), "n": int(g.get("n", 7)),
                          "spread": float(g.get("spread", 0.8)), "color": col,
                          "light": float(g.get("light", 1))})

    s["features"] = []
    for i, f in enumerate(d.get("features") or []):
        k = f.get("kind")
        if k not in FEATURE_KINDS:
            raise SpecError(f"features[{i}]: kind must be one of {', '.join(FEATURE_KINDS)}")
        s["features"].append({"kind": k, "at": _pt(f.get("at"), f"features[{i}]"),
                              "rot": math.radians(float(f.get("rot", 0))), "r": float(f.get("r", 1)),
                              "n": int(f.get("n", 5)), "lit": bool(f.get("lit", True)),
                              "to": _pt(f["to"], f"features[{i}].to") if f.get("to") else None,
                              "chained": bool(f.get("chained", False)), "label": f.get("label")})

    s["lights"] = []
    for i, l in enumerate(d.get("lights") or []):
        col = l.get("color", "torch")
        if col not in LIGHT_COLOURS:
            raise SpecError(f"lights[{i}]: color must be one of {', '.join(LIGHT_COLOURS)}")
        s["lights"].append({"at": _pt(l.get("at"), f"lights[{i}]"), "color": col,
                            "radius": float(l.get("radius", 4)), "bright": float(l.get("bright", 0))})
    return s


def all_lights(s):
    """Every light the map paints and exports: spec lights, lit fires/camps, glow clusters.
    radius/bright are in cells; Foundry export turns them into feet."""
    out = [dict(l, rgb=LIGHT_COLOURS[l["color"]]) for l in s["lights"]]
    for f in s["features"]:
        if f["kind"] in ("camp", "fire") and f["lit"]:
            at = f["at"]
            if f["kind"] == "camp":  # the fire sits right of the bedroll in the camp's own frame
                c, si = math.cos(f["rot"]), math.sin(f["rot"])
                at = (at[0] + 1.6 * c, at[1] + 1.6 * si)
            out.append({"at": at, "color": "fire", "rgb": LIGHT_COLOURS["fire"], "radius": 6, "bright": 2, "fire": True})
    for f in s["features"]:
        if f["kind"] == "torch" and f["lit"]:
            out.append({"at": f["at"], "color": "torch", "rgb": LIGHT_COLOURS["torch"], "radius": 5, "bright": 2, "fire": True})
        if f["kind"] == "moonbeam":
            out.append({"at": f["at"], "color": "moon", "rgb": LIGHT_COLOURS["moon"], "radius": 2.6 * f["r"],
                        "bright": f["r"], "beam": True})
    for f in s["features"]:
        if f["kind"] == "brazier" and f["lit"]:
            out.append({"at": f["at"], "color": "fire", "rgb": LIGHT_COLOURS["fire"], "radius": 5, "bright": 2, "fire": True})
    for lv in s["lava"]:  # lava glows along its whole length: a light every three cells
        pts = lv.get("pts") or [lv["at"]]
        seq = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 3))
            seq += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(1, n + 1)]
        rad = 3 + (max(lv["r"]) if "r" in lv else lv["width"])
        for q in seq:
            out.append({"at": q, "color": "lava", "rgb": LIGHT_COLOURS["lava"], "radius": rad, "bright": 1, "lava": True})
    for g in s["glow"]:
        if g["light"] > 0:
            out.append({"at": g["at"], "color": g["color"], "rgb": GLOW_COLOURS[g["color"]],
                        "radius": 2.2 * g["light"], "bright": 0, "glow": True})
    return out
