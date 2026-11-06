#!/usr/bin/env python3
"""Paint a cave battlemap from a cave spec, in the eight steps of a hand-drawn cave map.

  cave-map SPEC --check                                 spec + QA only
  cave-map SPEC [--px 100] [--preview p.png] [--steps DIR] [--dm] [--out-dir DIR]

SPEC is a .yaml file, or a Markdown note holding a ```cave fence. Writes <slug>.webp and
<slug>-foundry.json (walls + lights) into --out-dir (default: the spec's folder).
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from . import dress as cavedress
from . import field as F
from . import spec as cavespec
from .foundry import foundry_doc

PAPER = np.array([214, 194, 158], np.float32) / 255
FLOOR = np.array([170, 150, 120], np.float32) / 255
RIDGE = np.array([122, 108, 94], np.float32) / 255
DEEP = np.array([72, 66, 62], np.float32) / 255
DAMP = np.array([84, 112, 78], np.float32) / 255
WATER = np.array([70, 92, 100], np.float32) / 255
BLOOD = np.array([112, 30, 26], np.float32) / 255
INK = np.array([40, 31, 27], np.float32) / 255
NIGHT = np.array([54, 64, 100], np.float32) / 255
LAVA = np.array([255, 104, 30], np.float32) / 255
LAVA_HOT = np.array([255, 214, 120], np.float32) / 255
CRUST = np.array([70, 30, 20], np.float32) / 255
SOOT = np.array([30, 26, 25], np.float32) / 255


def slope(d, px):
    """|grad d| in cells per cell; near 1 except at saddles, where it would fatten lines."""
    gy, gx = np.gradient(d)
    return np.maximum(np.hypot(gx, gy) * px, 0.35)


def band(d, at, half, px, g=None):
    """Anti-aliased line where d == at; half-width in cells. g = slope(d) keeps width even."""
    dist = np.abs(d - at) if g is None else np.abs(d - at) / g
    return np.clip(1 - (dist - half) * px, 0, 1)


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def over(img, col, alpha):
    """img (h,w,3) blended toward col (3,) or (h,w,3) by alpha (h,w)."""
    a = alpha[..., None]
    img *= 1 - a
    img += a * col
    return img


def paper(h, w, s, res):
    grain = F.noise(s["W"], s["H"], res, 0.15, [s["seed"], 40]) * 0.025
    blot = F.fbm(s["W"], s["H"], res, 4.0, [s["seed"], 41], 2) * 0.04
    return np.clip(PAPER[None, None, :] * (1 + grain + blot)[..., None], 0, 1)


def wall_ink(s, d1, dj, px, res, stage, ledge=None, chasm=None):
    """Steps one to three: the outline, the jagged line, then depth lines behind and in front."""
    if stage == 1:
        return band(d1, 0, 0.05, px, slope(d1, px))
    g = slope(dj, px)
    ink = band(dj, 0, 0.028, px, g)
    if stage == 2:
        return ink
    k = s["seed"]
    lines = [(0.17, 0.022, 1.0), (0.38, 0.018, 0.8), (0.66, 0.015, 0.45), (1.0, 0.012, 0.2), (-0.1, 0.012, 0.55)]
    for i, (off, half, keep) in enumerate(lines):
        wob = 0.05 * F.noise(s["W"], s["H"], res, 0.6, [k, 50 + i])
        line = band(dj + wob, off, half, px, g)
        if keep < 1:  # broken strokes on the outermost lines give the wall its texture
            gate = smooth(0.15 - keep, 0.35 - keep, F.noise(s["W"], s["H"], res, 0.5, [k, 60 + i]))
            line *= gate
        ink = np.maximum(ink, line * (0.85 if off > 0 else 0.6))
    gate = smooth(-0.2, 0.15, F.noise(s["W"], s["H"], res, 0.5, [k, 70]))
    if ledge is not None:  # a ledge: its lip, and a broken line where the drop meets the floor below
        gl = slope(ledge, px)
        ink = np.maximum(ink, band(ledge, 0, 0.024, px, gl))
        ink = np.maximum(ink, band(ledge, 0.16, 0.013, px, gl) * gate * 0.7)
    if chasm is not None:  # a pit: lines stepping down into it
        gc = slope(chasm, px)
        for off, half, a in ((0, 0.026, 1), (-0.18, 0.016, 0.8), (-0.42, 0.012, 0.55), (-0.75, 0.01, 0.35)):
            ink = np.maximum(ink, band(chasm, off, half, px, gc) * (a if off == 0 else a * gate))
    return ink


def scorch_field(s, res):
    fs = [f for f in s["features"] if f["kind"] == "scorch"]
    if not fs:
        return None
    X, Y = F.grid(s["W"], s["H"], res)
    b = np.full(X.shape, 9.0, np.float32)
    for f in fs:
        b = np.minimum(b, F.sd_ellipse(X, Y, f["at"], (f["r"], f["r"] * 0.85), f["rot"]))
    return b + 0.5 * F.fbm(s["W"], s["H"], res, 0.9, [s["seed"], 160], 3)


def blood_field(s, res):
    fs = [f for f in s["features"] if f["kind"] in ("blood", "camp", "carcass")]
    if not fs:
        return None
    X, Y = F.grid(s["W"], s["H"], res)
    b = np.full(X.shape, 9.0, np.float32)
    for f in fs:
        r = f["r"] if f["kind"] == "blood" else 0.45
        at = f["at"]
        if f["kind"] == "camp":  # a dark stain on the bedroll, as in the tutorial's camp
            c, si = math.cos(f["rot"]), math.sin(f["rot"])
            at = (at[0] - 0.25 * si, at[1] + 0.25 * c)
        b = np.minimum(b, F.sd_ellipse(X, Y, at, (r, r * 0.8), f["rot"]))
    return b + 0.35 * F.fbm(s["W"], s["H"], res, 0.6, [s["seed"], 70], 3)


def light_maps(s, dj, res):
    """Per-pixel light colour (h,w,3) and intensity (h,w), walls stopping the light."""
    lr = 4
    small = F.resample(dj, s["W"] * lr, s["H"] * lr)
    block = (small > 0.35).astype(np.float32)
    X, Y = F.grid(s["W"], s["H"], lr)
    col = np.zeros((*small.shape, 3), np.float32)
    inten = np.zeros(small.shape, np.float32)
    for L in cavespec.all_lights(s):
        vis = F.visibility(block, lr, L["at"])
        dist = np.hypot(X - L["at"][0], Y - L["at"][1])
        fall = np.exp(-((dist / L["radius"]) ** 2) * 2.2) * vis * (1.25 if L.get("fire") else 0.9)
        inten += fall
        col += fall[..., None] * (np.array(L["rgb"], np.float32) / 255)
    col /= np.maximum(inten, 1e-4)[..., None]
    h, w = dj.shape
    inten = F.resample(inten, w, h)
    col = np.stack([F.resample(col[..., i], w, h) for i in range(3)], -1)
    tex = 0.85 + 0.15 * F.fbm(s["W"], s["H"], res, 0.8, [s["seed"], 80], 2)
    return np.clip(col, 0, 1), np.clip(inten * tex, 0, 1.6)


def render(s, px, want_steps=False):
    W, H = s["W"], s["H"]
    h, w = H * px, W * px
    steps = {}
    d1, dj = F.fields(s, px)
    logic = F.fields(s, cavedress.LOGIC_RES)[1]
    placed = cavedress.place(s, logic)
    pool = F.water_field(s, px, True)
    puddle = F.water_field(s, px, False, placed["puddles"])
    ledge = F.shape_field(s, px, "ledges", 120)
    chasm = F.shape_field(s, px, "chasms", 130)
    lava = F.lava_field(s, px)
    details = cavedress.draw(s, placed, px, (w, h))
    det = np.asarray(details, np.float32) / 255
    det_rgb, det_a = det[..., :3], det[..., 3]

    fmask = smooth(0.02, -0.06, dj)

    def water_lines(img):
        for fld, deep in ((pool, True), (puddle, False)):
            if fld is None:
                continue
            gate = smooth(-0.3, 0.1, F.noise(W, H, px, 0.45, [s["seed"], 90 + deep])) * fmask
            over(img, INK, band(fld, 0, 0.014, px) * gate * (0.8 if deep else 0.5))
            if deep:
                over(img, INK, band(fld, -0.45, 0.01, px) * gate * 0.35)
        return img

    if want_steps:
        base = paper(h, w, s, px)
        for st in (1, 2, 3):
            steps[st] = over(base.copy(), INK, wall_ink(s, d1, dj, px, px, st, ledge, chasm))
        s4 = water_lines(steps[3].copy())
        steps[4] = over(s4, det_rgb, det_a)
        del base, s4

    # step five: diffuse earth tones, damp green wash along the walls, water, blood
    tex = F.fbm(W, H, px, 3.0, [s["seed"], 100], 3)
    img = np.empty((h, w, 3), np.float32)
    rock_t = smooth(0.0, 3.5, dj)[..., None]
    img[:] = RIDGE * (1 - rock_t) + DEEP * rock_t
    floor = smooth(0.02, -0.06, dj)
    over(img, FLOOR, floor)
    img *= (1 + 0.07 * tex + 0.03 * F.noise(W, H, px, 0.2, [s["seed"], 101]))[..., None]
    damp = smooth(-1.1, -0.05, dj) * floor * smooth(-0.2, 0.5, F.fbm(W, H, px, 1.5, [s["seed"], 102], 2))
    over(img, DAMP, damp * 0.38 * s["damp"])
    if ledge is not None:  # raised floor reads lighter; its drop throws a shadow on the floor below
        over(img, np.clip(FLOOR * 1.14, 0, 1), smooth(0.02, -0.08, ledge) * floor)
        over(img, DEEP * 0.7, smooth(0.5, 0.0, ledge) * (ledge > 0) * floor * 0.5)
    if chasm is not None:
        inside = smooth(0.02, -0.1, chasm) * floor
        over(img, np.array([0.05, 0.045, 0.05], np.float32), inside * (0.55 + 0.45 * smooth(0, -1.2, chasm)))
    X, Y = F.grid(W, H, px)
    for f in s["features"]:
        if f["kind"] == "moonbeam":  # the pool of moonlight on the floor under a crack in the ceiling
            disc = np.exp(-((np.hypot(X - f["at"][0], Y - f["at"][1]) / f["r"]) ** 2) * 1.6)
            over(img, np.array([0.80, 0.85, 0.94], np.float32), disc * 0.45 * floor)
    for fld, deep in ((pool, True), (puddle, False)):
        if fld is not None:
            wet = smooth(0.05, -0.1, fld) * floor
            over(img, WATER * (0.75 if deep else 1.05), wet * (0.55 + 0.3 * smooth(0, -1.5, fld) if deep else 0.3))
    sc = scorch_field(s, px)
    if sc is not None:  # soot: darkest at the heart, feathered out with the brush texture
        over(img, SOOT, smooth(0.25, -0.9, sc) * 0.55 * floor)
    if lava is not None:  # the cooled crust round a lava flow, before the glow goes on top in step seven
        over(img, CRUST, smooth(0.45, 0.0, lava) * floor * 0.85)
    bl = blood_field(s, px)
    if bl is not None:
        over(img, BLOOD, smooth(0.05, -0.15, bl) * 0.55 * floor)
    img = water_lines(img)
    over(img, det_rgb, det_a)
    over(img, INK, wall_ink(s, d1, dj, px, px, 3, ledge, chasm))
    np.clip(img, 0, 1, out=img)
    lit_base = img.copy()
    if want_steps:
        steps[5] = img.copy()

    # step six: one dark blue layer over everything
    night = img * (1 - s["darkness"]) + img * NIGHT * 1.15 * s["darkness"]
    if want_steps:
        steps[6] = night.copy()

    # step seven: highlights round the lights, blue shade built from the outside in,
    # heaviest at the foot of the walls and nearest the lights
    lcol, li = light_maps(s, dj, px)
    reveal = np.clip(li, 0, 1)[..., None]
    out = night * (1 - reveal) + lit_base * (0.55 + 0.45 * lcol) * reveal
    out += (lcol * np.clip(li - 0.35, 0, 1)[..., None] * 0.35) * (1 - out)
    foot = np.exp(-np.clip(-dj, 0, None) / 0.32) * (dj < 0.05)
    shade = np.clip(0.42 * foot * (0.7 + 0.5 * np.clip(li, 0, 1)) + 0.45 * smooth(0.3, 4.0, dj), 0, 0.85)
    out = out * (1 - shade[..., None]) + out * NIGHT * 0.5 * shade[..., None]
    if chasm is not None:
        out *= (1 - 0.6 * smooth(0, -1.0, chasm))[..., None]
    if lava is not None:  # lava burns through the night layer: its own light, hot cracks over cooling plates
        core = smooth(0.0, -0.12, lava) * floor
        heat = smooth(-0.1, 0.5, F.fbm(W, H, px, 0.8, [s["seed"], 151], 3))
        plates = smooth(0.25, 0.45, F.noise(W, H, px, 0.6, [s["seed"], 152])) * smooth(-0.1, -0.5, lava)
        col = LAVA * (1 - heat[..., None]) + LAVA_HOT * heat[..., None]
        col = col * (1 - plates[..., None]) + CRUST * 1.3 * plates[..., None]
        over(out, col, core)
        gate = smooth(-0.2, 0.2, F.noise(W, H, px, 0.4, [s["seed"], 153]))
        over(out, INK, band(lava, 0.0, 0.016, px, slope(lava, px)) * gate * floor * 0.8)
    edge = np.minimum(np.minimum(X, W - X), np.minimum(Y, H - Y))
    out *= (0.82 + 0.18 * smooth(0, 3, edge))[..., None]
    out = np.clip(out, 0, 1)
    steps[7] = out
    return steps, {"d1": d1, "dj": dj, "logic": logic, "placed": placed}


def to_image(a):
    return Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def with_grid(im, px):
    im = im.copy()
    from PIL import ImageDraw
    d = ImageDraw.Draw(im, "RGBA")
    for x in range(0, im.width, px):
        d.line([(x, 0), (x, im.height)], fill=(255, 255, 255, 40))
    for y in range(0, im.height, px):
        d.line([(0, y), (im.width, y)], fill=(255, 255, 255, 40))
    return im


def islands(mask):
    """(area, first sample) of every 4-connected component of mask not touching the map edge."""
    h, w = mask.shape
    seen = np.zeros_like(mask)
    out = []
    for i0, j0 in zip(*np.nonzero(mask)):
        if seen[i0, j0]:
            continue
        seen[i0, j0] = True
        stack, area, edge = [(i0, j0)], 0, False
        while stack:
            i, j = stack.pop()
            area += 1
            edge |= i in (0, h - 1) or j in (0, w - 1)
            for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= a < h and 0 <= b < w and mask[a, b] and not seen[a, b]:
                    seen[a, b] = True
                    stack.append((a, b))
        if not edge:
            out.append((area, (i0, j0)))
    return out


def with_labels(im, s, px):
    """DM-only overlay: room tags (chamber, ledge, feature and passage `label`s), secret passages as
    dashed red lines and traps as red crosses. On the preview and the --dm copy, never on the map."""
    from PIL import ImageDraw, ImageFont
    d = ImageDraw.Draw(im, "RGBA")
    red = (230, 40, 40, 255)
    w = max(2, px // 12)
    for p in s["passages"]:
        if not p["secret"]:
            continue
        for a, b in zip(p["pts"], p["pts"][1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            n = max(2, int(L / 0.5))
            for k in range(0, n, 2):
                t0, t1 = k / n, min(1, (k + 1) / n)
                d.line([((a[0] + (b[0] - a[0]) * t0) * px, (a[1] + (b[1] - a[1]) * t0) * px),
                        ((a[0] + (b[0] - a[0]) * t1) * px, (a[1] + (b[1] - a[1]) * t1) * px)], fill=red, width=w)
    for f in s["features"]:
        if f["kind"] == "trap":
            x, y, r = f["at"][0] * px, f["at"][1] * px, 0.4 * px
            d.line([(x - r, y - r), (x + r, y + r)], fill=red, width=w)
            d.line([(x - r, y + r), (x + r, y - r)], fill=red, width=w)
    try:
        font = ImageFont.load_default(size=max(11, int(px * 0.6)))
    except TypeError:
        font = ImageFont.load_default()
    mids = [dict(p, at=p["pts"][len(p["pts"]) // 2]) for p in s["passages"]]
    for it in [*s["chambers"], *s["ledges"], *s["features"], *mids]:
        if it.get("label"):
            x, y = it["at"][0] * px, it["at"][1] * px
            d.text((x, y), str(it["label"]), font=font, fill=(255, 236, 160, 255), anchor="mm",
                   stroke_width=3, stroke_fill=(0, 0, 0, 255))
    return im


def qa(s, logic):
    """FAIL = not a usable map; WARN = look at it."""
    res = cavedress.LOGIC_RES
    fails, warns = [], []
    open_ = logic < -0.5  # a centre point half a cell from any wall: a 5-ft creature fits
    h, w = logic.shape

    def cell(p):
        return int(np.clip(p[1] * res, 0, h - 1)), int(np.clip(p[0] * res, 0, w - 1))

    for c in s["chambers"]:
        if not open_[cell(c["at"])]:
            fails.append(f"chamber {c['id']}: its centre is not open floor (pillar or wall over it?)")
    start = next((cell(c["at"]) for c in s["chambers"] if open_[cell(c["at"])]), None)
    if start:
        seen = np.zeros_like(open_)
        stack = [start]
        seen[start] = True
        while stack:
            i, j = stack.pop()
            for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= a < h and 0 <= b < w and open_[a, b] and not seen[a, b]:
                    seen[a, b] = True
                    stack.append((a, b))
        for c in s["chambers"]:
            if open_[cell(c["at"])] and not seen[cell(c["at"])]:
                fails.append(f"chamber {c['id']}: no 5-ft-wide path to {s['chambers'][0]['id']} (widen the passage)")
    secret = {p["where"] for p in s["passages"] if p["secret"]}
    for where, q in s.get("exits", []):
        if where in secret:
            continue
        x, y = min(max(q[0], 0.5), s["W"] - 0.5), min(max(q[1], 0.5), s["H"] - 0.5)
        if not open_[cell((x, y))]:
            warns.append(f"{where}: the exit does not open on the map edge at ({x:.0f}, {y:.0f})")
    for kind, items in (("feature", s["features"]), ("glow", s["glow"]), ("light", s["lights"])):
        for i, it in enumerate(items):
            wall_ok = it.get("kind") in ("torch", "web", "roots", "claws", "chains")  # hung on or grown from the wall
            if logic[cell(it["at"])] > (0.4 if wall_ok else -0.05):
                warns.append(f"{kind}[{i}] at {it['at']}: sits in the rock")
    for area, (i, j) in islands(logic > 0):
        if area < 2.5 * res * res:
            warns.append(f"a rock speck of {area / res / res:.1f} cells near ({j / res:.0f}, {i / res:.0f}): "
                         "two shapes almost touch; open them up with a passage or move them apart")
    for c in s["chambers"]:
        for q in s["chasms"]:
            if math.hypot(c["at"][0] - q["at"][0], c["at"][1] - q["at"][1]) < min(q["r"]):
                warns.append(f"chamber {c['id']}: its centre is in a chasm")
    frac = float((logic < 0).mean())
    if not 0.2 <= frac <= 0.8:
        warns.append(f"open floor is {frac:.0%} of the map (aim for 20–80%)")
    if not cavespec.all_lights(s):
        warns.append("no light at all: the night layer will leave a black map")
    return fails, warns, frac


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("note", metavar="SPEC")
    ap.add_argument("--check", action="store_true", help="spec + QA only, no painting")
    ap.add_argument("--px", type=int, help="pixels per 5-ft cell (spec px, default 100)")
    ap.add_argument("--out-dir", help="where the map and foundry json go (default: the spec's folder)")
    ap.add_argument("--out", help="map path (overrides --out-dir for the image)")
    ap.add_argument("--preview", help="also write a small gridded preview here (.png/.webp)")
    ap.add_argument("--preview-px", type=int, default=28)
    ap.add_argument("--steps", help="write the tutorial's step images 1–7 into this folder (at --preview-px)")
    ap.add_argument("--no-map", action="store_true", help="skip the full-size map (with --preview/--steps)")
    ap.add_argument("--dm", action="store_true", help="also write <slug>-dm.webp: the map with tags, secret ways and traps")
    a = ap.parse_args(argv)

    try:
        s = cavespec.normalise(cavespec.read_fence(a.note))
    except cavespec.SpecError as e:
        print(f"SPEC ERROR: {e}")
        return 2
    logic = F.fields(s, cavedress.LOGIC_RES)[1]
    fails, warns, frac = qa(s, logic)
    print(f"{s['name']}: {s['W']}×{s['H']} cells ({s['W'] * 5}×{s['H'] * 5} ft), floor {frac:.0%}, "
          f"{len(cavespec.all_lights(s))} lights")
    if a.check:
        return report(s, fails, warns)

    if a.steps:
        st, _ = render(s, a.preview_px, want_steps=True)
        Path(a.steps).mkdir(parents=True, exist_ok=True)
        for k, im in st.items():
            to_image(im).save(Path(a.steps) / f"step-{k}.png")
        print(f"steps 1–7 → {a.steps}")
    if a.preview:
        st, _ = render(s, a.preview_px)
        with_labels(with_grid(to_image(st[7]), a.preview_px), s, a.preview_px).save(a.preview)
        print(f"preview → {a.preview}")
    if not a.no_map:
        px = a.px or s["px"]
        st, f = render(s, px)
        od = Path(a.out_dir) if a.out_dir else Path(a.note).parent
        out = Path(a.out) if a.out else od / f"{s['slug']}.webp"
        out.parent.mkdir(parents=True, exist_ok=True)
        to_image(st[7]).save(out, "WEBP", quality=86, method=6)
        if a.dm:
            dm = out.with_name(out.stem + "-dm.webp")
            with_labels(to_image(st[7]), s, px).save(dm, "WEBP", quality=86, method=6)
            print(f"dm copy → {dm}")
        doc = foundry_doc(s, f["dj"], px, out)
        jp = od / f"{s['slug']}-foundry.json"
        jp.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"map → {out} ({out.stat().st_size // 1024} KB, {px} px/cell)\n"
              f"foundry → {jp} ({len(doc['walls'])} walls, {len(doc['lights'])} lights)")
    return report(s, fails, warns)


def report(s, fails, warns):
    for m in fails:
        print(f"FAIL {m}")
    for m in warns:
        print(f"WARN {m}")
    print(f"QA {s['name']}: {len(fails)} FAIL, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
