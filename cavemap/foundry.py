"""Foundry scene data for a painted cave: walls traced along the drawn wall line, and lights.

Walls come from marching squares on the jagged field at WALL_RES samples per cell, chained
into polylines and simplified, so a wall follows the ink within about a tenth of a cell.
Coordinates are scene pixels at the map's px per cell; light radii are in feet.
"""
import math

import numpy as np

from . import field as F
from . import spec as cavespec

WALL_RES = 4
TOL = 0.12  # cells


def _segments(f):
    """Marching squares on f (rock > 0); returns segments in sample coordinates."""
    h, w = f.shape
    segs = []
    a, b, c, d = f[:-1, :-1], f[:-1, 1:], f[1:, 1:], f[1:, :-1]
    idx = (a > 0) * 1 + (b > 0) * 2 + (c > 0) * 4 + (d > 0) * 8

    def lerp(v0, v1):
        return v0 / (v0 - v1 + 1e-9)

    for i, j in zip(*np.nonzero((idx > 0) & (idx < 15))):
        A, B, C, D = a[i, j], b[i, j], c[i, j], d[i, j]
        top = (j + lerp(A, B), i)
        right = (j + 1, i + lerp(B, C))
        bot = (j + lerp(D, C), i + 1)
        left = (j, i + lerp(A, D))
        k = idx[i, j]
        pairs = {1: [(left, top)], 2: [(top, right)], 3: [(left, right)], 4: [(right, bot)],
                 5: [(left, top), (right, bot)], 6: [(top, bot)], 7: [(left, bot)], 8: [(bot, left)],
                 9: [(bot, top)], 10: [(top, right), (bot, left)], 11: [(bot, right)], 12: [(right, left)],
                 13: [(right, top)], 14: [(top, left)]}[k]
        segs += pairs
    return segs


def _chain(segs):
    key = lambda p: (round(p[0], 4), round(p[1], 4))  # noqa: E731
    adj = {}
    for s in segs:
        adj.setdefault(key(s[0]), []).append(s)
        adj.setdefault(key(s[1]), []).append(s)
    used = set()
    lines = []
    for s in segs:
        if id(s) in used:
            continue
        used.add(id(s))
        line = [s[0], s[1]]
        for end in (1, 0):
            while True:
                p = line[-1] if end else line[0]
                nxt = next((t for t in adj[key(p)] if id(t) not in used), None)
                if nxt is None:
                    break
                used.add(id(nxt))
                q = nxt[1] if key(nxt[0]) == key(p) else nxt[0]
                if end:
                    line.append(q)
                else:
                    line.insert(0, q)
        lines.append(line)
    return lines


def _rdp(pts, tol):
    if len(pts) < 3:
        return pts
    a, b = np.array(pts[0]), np.array(pts[-1])
    ab = b - a
    n = np.hypot(*ab)
    P = np.array(pts[1:-1])
    if n < 1e-9:
        dist = np.hypot(*(P - a).T)
    else:
        dist = np.abs(ab[0] * (P[:, 1] - a[1]) - ab[1] * (P[:, 0] - a[0])) / n
    k = int(np.argmax(dist))
    if dist[k] > tol:
        return _rdp(pts[: k + 2], tol)[:-1] + _rdp(pts[k + 1:], tol)
    return [pts[0], pts[-1]]


def wall_lines(s, dj, res=None, field=None):
    """The drawn wall line as simplified polylines in cells. `field` traces another field (a ledge's lip)."""
    f = field if field is not None else dj
    f = F.resample(f, s["W"] * WALL_RES, s["H"] * WALL_RES)
    f = np.pad(f, 1, mode="edge")  # no wall along the map border, so exits stay open
    out = []
    for line in _chain(_segments(f)):
        pts = [((x - 1 + 0.5) / WALL_RES, (y - 1 + 0.5) / WALL_RES) for x, y in line]
        pts = [p for p in pts if -0.01 <= p[0] <= s["W"] + 0.01 and -0.01 <= p[1] <= s["H"] + 0.01]
        pts = _rdp(pts, TOL)
        if len(pts) > 1:
            out.append(pts)
    return out


def walls(s, dj, px):
    out = []
    for pts in wall_lines(s, dj):
        for p, q in zip(pts, pts[1:]):
            out.append({"c": [round(p[0] * px), round(p[1] * px), round(q[0] * px), round(q[1] * px)],
                        "move": 20, "sight": 20, "light": 20, "sound": 20})
    return out


def lights(s, px):
    out = []
    for L in cavespec.all_lights(s):
        r, g, b = L["rgb"]
        out.append({"x": round(L["at"][0] * px), "y": round(L["at"][1] * px),
                    "config": {"dim": round(L["radius"] * 5 * (0.5 if L.get("glow") else 1)),
                               "bright": round(L.get("bright", 0) * 5),
                               "color": f"#{r:02x}{g:02x}{b:02x}", "alpha": 0.35 if L.get("fire") else 0.25,
                               "animation": {"type": "torch" if L.get("fire") else "pulse",
                                             "speed": 3 if L.get("fire") else 1, "intensity": 3 if L.get("fire") else 2}}})
    return out


def foundry_doc(s, dj, px, image):
    return {
        "name": s["name"],
        "background": {"src": str(image).replace("\\", "/")},
        "width": s["W"] * px, "height": s["H"] * px, "padding": 0,
        "grid": {"size": px, "distance": 5, "units": "ft", "type": 1},
        "environment": {"globalLight": {"enabled": False}, "darknessLevel": 0.85},
        "walls": walls(s, dj, px),
        "lights": lights(s, px),
    }
