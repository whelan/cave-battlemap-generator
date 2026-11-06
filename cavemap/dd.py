#!/usr/bin/env python3
"""Build the same cave as a Dungeondraft map, dressed with Forgotten Adventures assets.

  cave-dd SPEC --plan      anywhere: what goes where, no packs needed
  cave-dd SPEC [--check]   needs Dungeondraft's custom assets folder (DDMAP_ASSETS or its config.ini)

Same spec, same seed, same placements as the painted map: cave floor, rock and water as terrain,
rock walls along the traced wall line, a cave ridge along every ledge, and every rubble stone, nest,
cage, mushroom and light as a pack object. Writes <spec dir>/<slug>.dungeondraft_map.
"""
import argparse
import math
import os
import random
import sys
from pathlib import Path

import numpy as np

from . import dress as cavedress
from . import field as F
from . import spec as cavespec
from .foundry import wall_lines

RUG, FURN, TOP, HIGH = 100, 200, 300, 700

# kind -> list of (regex, cells, layer); regexes match res paths in the pack index ("/" anchors a name)
ASSETS = {
    "rock": [(r"/Rock_Stone_Slate_(1x1|A)", 0.8, RUG)],
    "stalagmite": [(r"/Boulder_Stone_Slate_", 1.0, FURN)],
    "nest": [(r"/Hay_Pile", 1.8, RUG), (r"/TC_Fur Blanket 01_2x1\.", 1.4, RUG)],
    "cage": [(r"/Cage_Metal_Rusty_", 2.0, FURN)],
    "corpse": [(r"/Skeleton_Humanoid_Yellowed", 1.8, RUG), (r"/Chain_Metal_Rusty_Wall_Manacles", 0.8, FURN)],
    "chains": [(r"/Chain_Metal_Rusty_Wall_Manacles", 0.8, FURN)],
    "statue": [(r"/Prefab_Grave_Statue_Prayer", 2.0, FURN)],
    "treasure": [(r"/Coins", 1.2, RUG), (r"/Coin_Gold", 0.5, TOP)],
    "torch": [(r"/Sconce_Orange_.*_Lit|/Sconce", 0.8, HIGH)],
    "tracks": [(r"/Footprint_Set_Wolf_01_A", 1.0, RUG)],
    "web": [(r"/Cobweb_White", 1.4, HIGH)],
    "moss": [(r"/Moss_.*_Green_Pile", 1.4, RUG)],
    "skull": [(r"/Skull_Decor_Cracked", 0.6, RUG)],
    "bones": [(r"/Bone_Yellowed_(Ribcage|Spine|Pelvis)", 0.9, RUG)],
    "spear": [(r"/Spear_Standing", 1.2, TOP)],
    "fire": [(r"/Campfire_Lit_01_A", 1.4, RUG)],
    "bedroll": [(r"/Bedroll_Brown", 2.0, RUG)],
    "pack": [(r"/Backpack_Brown", 0.8, FURN)],
    "blood": [(r"/Blood_Puddle", 1.6, RUG)],
    "carcass": [(r"/Bone_Yellowed_Ribcage", 2.2, RUG), (r"/Deer_Skull_01_A", 1.2, RUG), (r"/Blood_Puddle", 2.6, RUG)],
    "crate": [(r"/Box_Crate_Wood_Dark_", 1.0, FURN)],
    "altar": [(r"/Cultists Ritual Altar Prefab 01", 3.0, FURN)],
    "puddle": [(r"/Puddle_Transparent_01_A", 1.6, RUG)],
    "stairs": [(r"/Stairs_Stone_Slate_", None, RUG)],
    "brazier": [(r"/Brazier_Orange_.*_Lit|/Brazier", 1.0, FURN)],
    "scorch": [(r"AoA_Scorch/colorable/ScorchMarkColourable-1", 2.0, RUG), (r"AoA_Charr/CharMark-1", 1.6, RUG)],
    "charred": [(r"/Bone_(Black|Yellowed)_(Ribcage|Spine|Pelvis)", 0.9, RUG)],
    "lava": [(r"AoA_Charr/colorable/CharGlowColorable-1", 1.2, RUG), (r"Fire/FirePatchA01", 0.9, TOP)],
}
GLOW = {"amber": r"/Mushroom_Yellow", "teal": r"/Mushroom_Blue", "pale-blue": r"/Mushroom_Blue",
        "violet": r"/Mushroom_Violet", "sickly-green": r"/Mushroom_Green", "red": r"/Mushroom_Red"}
NO_ASSET = {"claws", "roots", "moonbeam", "trap"}  # drawn only in the painted map (moonbeam is a light here)

TERRAIN = [r"Dirt_Terrain/Cave_Floor", r"Dirt_Terrain/Rocky_Dirt", r"Water_Terrain/Water_Calm_.*_Brown|Water_Terrain/Water",
           r"Dirt_Terrain/Gravel_Light"]
WALL_TEX = r"walls/Rock-2-wall\."
RIDGE_TEX = r"Cliffs_and_Ridges/Ridge_Cave"
AMBIENT = "ff141822"


def argb(rgb, a=255):
    return "{:02x}{:02x}{:02x}{:02x}".format(a, *rgb)


def plan(s):
    """Every object as (kind, regex, x, y, rot_deg, cells, layer), independent of the packs."""
    logic = F.fields(s, cavedress.LOGIC_RES)[1]
    placed = cavedress.place(s, logic)
    rnd = random.Random(s["seed"] * 31 + 5)
    out = []

    def put(kind, x, y, rot=0.0, scale=1.0, only=None):
        for i, (pat, cells, layer) in enumerate(ASSETS[kind]):
            if only is not None and i != only:
                continue
            out.append((kind, pat, x, y, rot, (cells or 1) * scale, layer))

    for x, y, r in placed["rocks"]:
        put("rock", x, y, rnd.uniform(0, 360), r / 0.35)
    for x, y, r in placed["stal"]:
        put("stalagmite", x, y, rnd.uniform(0, 360), r / 0.3)
    for q in placed["puddles"]:
        put("puddle", q["at"][0], q["at"][1], math.degrees(q["rot"]), max(q["r"]))
    for x, y, r, col in placed["dots"]:
        out.append(("glow", GLOW[col], x, y, rnd.uniform(0, 360), 0.35 + r * 2, RUG))
    for x, y, a, L, ch in placed["bones"]:
        put("charred" if ch else "bones", x, y, math.degrees(a), L / 0.4)
    for lv in s["lava"]:  # no lava texture in the packs: fire patches and a glowing char mark stand in
        pts = lv.get("pts") or [lv["at"]]
        seq = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 1.5))
            seq += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(1, n + 1)]
        size = lv["width"] if "pts" in lv else 2 * max(lv["r"])
        for q in seq:
            put("lava", q[0], q[1], rnd.uniform(0, 360), size)
    for st in s["stairs"]:
        out.append(("stairs", ASSETS["stairs"][0][0], st["at"][0], st["at"][1],
                    math.degrees(st["rot"]) + (0 if st["down"] else 180), (st["w"], st["l"]), RUG))
    for f in s["features"]:
        k, (x, y), rot = f["kind"], f["at"], math.degrees(f["rot"])
        c, si = math.cos(f["rot"]), math.sin(f["rot"])
        if k in NO_ASSET or k in ("bones", "charred"):
            continue
        if k == "camp":
            put("bedroll", x, y, rot)
            put("pack", x - 1.0 * c + 0.6 * si, y - 1.0 * si - 0.6 * c, rot)
            put("fire", x + 1.6 * c, y + 1.6 * si)
            continue
        if k == "tracks":
            to = f["to"] or (x + 3 * c, y + 3 * si)
            L = math.hypot(to[0] - x, to[1] - y)
            ang = math.degrees(math.atan2(to[1] - y, to[0] - x)) + 90
            for i in range(max(1, int(L))):
                t = (i + 0.5) / max(1, int(L))
                put("tracks", x + (to[0] - x) * t, y + (to[1] - y) * t, ang)
            continue
        if k == "chains" and f["to"]:
            x, y = (x + f["to"][0]) / 2, (y + f["to"][1]) / 2
        if k == "treasure":
            for i in range(3):
                a = 2 * math.pi * i / 3
                put("treasure", x + 0.4 * f["r"] * math.cos(a), y + 0.3 * f["r"] * math.sin(a), rnd.uniform(0, 360), f["r"], 0)
            put("treasure", x, y, 0, 1, 1)
            continue
        if k == "corpse":
            put("corpse", x, y, rot + 90, 1, 0)
            if f["chained"]:
                put("corpse", x - 1.0 * si, y + 1.0 * c, rot, 1, 1)
            continue
        scale = f["r"] if k in ("nest", "cage", "statue", "moss", "web", "blood", "carcass", "scorch") else 1
        put(k, x, y, rot, scale)
    return out, placed


def terrain_splat(s, placed):
    res = 4
    _, dj = F.fields(s, res)
    deep = F.water_field(s, res, True)
    shallow = F.water_field(s, res, False, placed["puddles"])
    ledge = F.shape_field(s, res, "ledges", 120)
    w = np.zeros((s["H"] * res, s["W"] * res, 4), np.float32)
    rock = np.clip(dj * 3 + 0.5, 0, 1)
    w[..., 1] = rock
    w[..., 0] = 1 - rock
    for fld in (deep, shallow):
        if fld is not None:
            wet = np.clip(-fld * 3 + 0.3, 0, 1) * (1 - rock)
            w[..., 2] = np.maximum(w[..., 2], wet)
    if ledge is not None:
        w[..., 3] = np.clip(-ledge * 3, 0, 1) * (1 - rock) * 0.6
    w[..., 0] = np.clip(w[..., 0] - w[..., 2] - w[..., 3], 0, 1)
    tot = w.sum(-1, keepdims=True)
    w = w / np.maximum(tot, 1e-6) * 255
    q = np.floor(w).astype(np.int32)
    q[..., 0] += 255 - q.sum(-1)  # the four weights sum to 255
    return "PoolByteArray( " + ", ".join(map(str, q.reshape(-1).tolist())) + " )"


def build(s, note, check):
    from .ddwriter import C, Writer
    b = Writer(s["W"], s["H"], check=check)
    objs, placed = plan(s)
    _, dj = F.fields(s, cavedress.LOGIC_RES)
    objects = []
    for kind, pat, x, y, rot, cells, layer in objs:
        objects.append(b.fit(pat, x, y, rot, cells, layer))
    lights = []
    for L in cavespec.all_lights(s):
        rng, inten = ((6, 1.0) if L.get("fire") and L["color"] == "fire" else (5, 0.9) if L.get("fire")
                      else (L["radius"], 0.8) if L.get("lava")
                      else (4, 0.7) if L.get("beam") else (1.6, 0.6))
        lights.append(b.light(L["at"][0], L["at"][1], rng, inten, argb(L["rgb"])))
    walls = [{"points": b.pva([(x * C, y * C) for x, y in pts]), "texture": b.pick(WALL_TEX), "color": "ffffffff",
              "loop": False, "type": 0, "joint": 1, "normalize_uv": True, "shadow": True, "node_id": b.nid(),
              "portals": []} for pts in wall_lines(s, dj)]
    paths = []
    if s["ledges"]:
        lf = F.shape_field(s, cavedress.LOGIC_RES, "ledges", 120)
        for pts in wall_lines(s, dj, field=lf):
            p = b.fence(pts, b.pick(RIDGE_TEX), width=96)
            paths.append(p)
    W, H = s["W"], s["H"]
    cave = "PoolByteArray( " + ", ".join(["0"] * -(-((4 * W + 3) * (4 * H + 3)) // 8)) + " )"
    tex = [b.pick(t) for t in TERRAIN]
    level = {
        "label": "Cave", "environment": {"baked_lighting": True, "ambient_light": AMBIENT},
        "layers": {"-400": "Below Ground", "-100": "Below Water", "100": "User Layer 1", "200": "User Layer 2",
                   "300": "User Layer 3", "400": "User Layer 4", "700": "Above Walls", "900": "Above Roofs"},
        "shapes": {"polygons": [], "walls": []},
        "tiles": {"cells": "PoolIntArray( " + ", ".join(["-1"] * (W * H)) + " )", "colors": ["ffffffff"] * (W * H), "lookup": {}},
        "patterns": [], "walls": walls, "portals": [],
        "cave": {"bitmap": cave, "ground_color": "ff7f7e71", "wall_color": "ff7f7e71", "entrance_bitmap": cave,
                 "texture": "res://textures/caves/colorable/floor.png"},
        "terrain": {"enabled": True, "expand_slots": False, "smooth_blending": True,
                    **{f"texture_{i + 1}": t for i, t in enumerate(tex)}, "splat": terrain_splat(s, placed)},
        "water": {"disable_border": False}, "materials": {}, "paths": paths,
        "objects": objects, "lights": lights,
        "roofs": {"shade": True, "shade_contrast": 0.5, "sun_direction": 45, "roofs": []},
        "texts": [], "texts_vis": True,
    }
    b.levels = {"0": level}
    return b


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("note", metavar="SPEC")
    ap.add_argument("--plan", action="store_true", help="list the objects per kind and pattern; needs no packs")
    ap.add_argument("--check", action="store_true", help="list patterns that match no asset; write nothing")
    ap.add_argument("--out", help="the .dungeondraft_map to write")
    a = ap.parse_args(argv)
    s = cavespec.normalise(cavespec.read_fence(a.note))
    if a.plan:
        objs, _ = plan(s)
        counts = {}
        for kind, pat, *_ in objs:
            counts[(kind, pat)] = counts.get((kind, pat), 0) + 1
        for (kind, pat), n in sorted(counts.items()):
            print(f"{n:4d}  {kind:11s} {pat}")
        skipped = sorted({f["kind"] for f in s["features"] if f["kind"] in NO_ASSET})
        print(f"{len(objs)} objects, {len(cavespec.all_lights(s))} lights"
              + (f"; painted map only: {', '.join(skipped)}" if skipped else ""))
        return 0
    try:
        b = build(s, a.note, a.check)
    except SystemExit as e:
        print(f"Dungeondraft packs not reachable here ({e}). Run this on the Mac, or use --plan.")
        return 1
    if a.check:
        miss = sorted(set(b.missing or []))
        for m in miss:
            print(f"MISSING {m}")
        print(f"{len(miss)} patterns match nothing")
        return 1 if miss else 0
    out = Path(a.out or Path(a.note).parent / f"{s['slug']}.dungeondraft_map")
    out.parent.mkdir(parents=True, exist_ok=True)
    b.write(str(out))
    for w in b.warnings:
        print(f"WARNING: {w}")
    print(f"dungeondraft → {out} ({len(b.levels['0']['objects'])} objects, {len(b.levels['0']['walls'])} walls)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
