"""Distance fields and noise for the cave. All distances are in cells.

d > 0 is rock, d < 0 is open floor, d = 0 is the drawn wall line. The same seed gives the
same cave at any resolution: noise lattices are sized in cells and only resampled per px.
"""
import math

import numpy as np
from PIL import Image

BASE_RES = 10  # samples per cell for the smooth analytic field


def grid(W, H, res):
    xs = (np.arange(W * res, dtype=np.float32) + 0.5) / res
    ys = (np.arange(H * res, dtype=np.float32) + 0.5) / res
    return np.meshgrid(xs, ys)


def sd_ellipse(X, Y, at, r, rot=0.0):
    c, s = math.cos(rot), math.sin(rot)
    dx, dy = X - at[0], Y - at[1]
    u, v = c * dx + s * dy, -s * dx + c * dy
    k = np.sqrt((u / r[0]) ** 2 + (v / r[1]) ** 2)
    return (k - 1.0) * min(r)


def sd_capsule(X, Y, a, b, rad):
    bax, bay = b[0] - a[0], b[1] - a[1]
    pax, pay = X - a[0], Y - a[1]
    h = np.clip((pax * bax + pay * bay) / max(bax * bax + bay * bay, 1e-6), 0, 1)
    return np.hypot(pax - bax * h, pay - bay * h) - rad


def smin(a, b, k):
    h = np.maximum(k - np.abs(a - b), 0) / k
    return np.minimum(a, b) - h * h * k * 0.25


def resample(a, w, h):
    return np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((w, h), Image.BICUBIC))


def noise(W, H, res, scale, key):
    """Smooth value noise in [-1, 1]-ish; scale is the lattice spacing in cells."""
    rng = np.random.default_rng(key)
    gw, gh = int(math.ceil(W / scale)) + 3, int(math.ceil(H / scale)) + 3
    lat = rng.random((gh, gw), dtype=np.float32) * 2 - 1
    tw, th = max(2, round(gw * scale * res)), max(2, round(gh * scale * res))
    return resample(lat, tw, th)[: H * res, : W * res]


def fbm(W, H, res, scale, key, octaves=3):
    out = np.zeros((H * res, W * res), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        out += amp * noise(W, H, res, scale / 2 ** o, [*key, o])
        tot += amp
        amp *= 0.5
    return out / tot


def base_sdf(s):
    """The smooth, un-jittered cave at BASE_RES samples per cell (step one)."""
    X, Y = grid(s["W"], s["H"], BASE_RES)
    d = None
    for c in s["chambers"]:
        e = sd_ellipse(X, Y, c["at"], c["r"], c["rot"])
        d = e if d is None else smin(d, e, 2.0)
    for p in s["passages"]:
        if p["secret"]:  # a secret way stays rock on the map; the DM sees it on the preview
            continue
        for a, b in zip(p["pts"], p["pts"][1:]):
            d = smin(d, sd_capsule(X, Y, a, b, p["width"] / 2), 1.6)
    for q in s["pillars"]:
        d = -smin(-d, sd_ellipse(X, Y, q["at"], q["r"], q["rot"]), 1.0)
    return d


def fields(s, res):
    """Return (d_outline, d_jagged) at res samples per cell."""
    W, H, k = s["W"], s["H"], s["seed"]
    d0 = resample(base_sdf(s), W * res, H * res)
    r = s["roughness"]
    d1 = d0 + r * 0.32 * fbm(W, H, res, 5.0, [k, 1], 2)
    dj = d1 + r * (0.14 * fbm(W, H, res, 1.2, [k, 2], 2) + 0.05 * noise(W, H, res, 0.3, [k, 3]))
    return d1, dj


def water_field(s, res, deep, extra=()):
    """Deep pools (deep=True) or shallow water: shallow pools, streams and auto puddles."""
    X, Y = grid(s["W"], s["H"], res)
    p = None
    for q in [*s["pools"], *extra]:
        if q.get("deep", True) != deep:
            continue
        e = sd_ellipse(X, Y, q["at"], q["r"], q["rot"])
        p = e if p is None else np.minimum(p, e)
    if not deep:
        for st in s["streams"]:
            for a, b in zip(st["pts"], st["pts"][1:]):
                e = sd_capsule(X, Y, a, b, st["width"] / 2)
                p = e if p is None else smin(p, e, 0.6)
    if p is None:
        return None
    return p + 0.25 * fbm(s["W"], s["H"], res, 1.0, [s["seed"], 7 + deep], 2)


def lava_field(s, res):
    if not s["lava"]:
        return None
    X, Y = grid(s["W"], s["H"], res)
    p = None
    for lv in s["lava"]:
        if "pts" in lv:
            for a, b in zip(lv["pts"], lv["pts"][1:]):
                e = sd_capsule(X, Y, a, b, lv["width"] / 2)
                p = e if p is None else smin(p, e, 0.8)
        else:
            e = sd_ellipse(X, Y, lv["at"], lv["r"], lv["rot"])
            p = e if p is None else smin(p, e, 0.8)
    return p + 0.3 * fbm(s["W"], s["H"], res, 1.2, [s["seed"], 150], 3)


def shape_field(s, res, key, salt):
    """Union of the ellipses under s[key] (ledges, chasms), with a hand-drawn wobble."""
    if not s[key]:
        return None
    X, Y = grid(s["W"], s["H"], res)
    p = None
    for q in s[key]:
        e = sd_ellipse(X, Y, q["at"], q["r"], q["rot"])
        p = e if p is None else smin(p, e, 0.8)
    r = s["roughness"]
    return p + r * (0.18 * fbm(s["W"], s["H"], res, 1.5, [s["seed"], salt], 2)
                    + 0.05 * noise(s["W"], s["H"], res, 0.3, [s["seed"], salt + 1]))


def visibility(block, res, at, steps=48):
    """Fraction of light from `at` (cells) reaching each sample; block is 1 where rock stops it."""
    h, w = block.shape
    X, Y = grid(w // res, h // res, res)
    vis = np.ones_like(block)
    lx, ly = at
    for t in np.linspace(0.04, 0.96, steps, dtype=np.float32):
        sx = np.clip(((lx + (X - lx) * t) * res).astype(np.int32), 0, w - 1)
        sy = np.clip(((ly + (Y - ly) * t) * res).astype(np.int32), 0, h - 1)
        vis *= 1 - block[sy, sx]
    return vis
