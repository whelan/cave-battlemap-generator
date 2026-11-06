"""Step four: the details — rubble, glowing clusters, the vignette props.

Placement is decided on the fixed logic field (LOGIC_RES), so the same seed puts the same
rock in the same place at every render size. Drawing happens per px on an RGBA layer.
"""
import math
import random

from PIL import Image, ImageDraw, ImageFilter

from .spec import GLOW_COLOURS

LOGIC_RES = 8
INK = (40, 31, 27, 255)
STONE = (128, 116, 104, 255)
STONE_LIT = (156, 144, 130, 255)


def _d(dj, x, y):
    h, w = dj.shape
    i, j = int(y * LOGIC_RES), int(x * LOGIC_RES)
    if not (0 <= i < h and 0 <= j < w):
        return 9.0
    return float(dj[i, j])


def place(s, dj):
    """Deterministic auto details: rubble groups hugging the walls, a few loose stones, puddles,
    and the dots of every glow cluster."""
    rnd = random.Random(s["seed"] * 7919 + 17)
    taken = [(f["at"], 1.8) for f in s["features"]] + [(g["at"], g["spread"] + 0.6) for g in s["glow"]]
    taken += [(q["at"], max(q["r"]) + 0.6) for q in s["pools"]]

    def free(x, y, r):
        return all(math.hypot(x - a[0], y - a[1]) > r + rr for a, rr in taken)

    rocks = []
    tries = 0
    while len(rocks) < s["rocks"] and tries < 4000:
        tries += 1
        x, y = rnd.uniform(0.5, s["W"] - 0.5), rnd.uniform(0.5, s["H"] - 0.5)
        dv = _d(dj, x, y)
        hug = len(rocks) % 4 != 3  # three of four sit against a wall, the fourth lies loose
        if not ((-0.85 < dv < -0.3) if hug else (dv < -1.5)) or not free(x, y, 0.5):
            continue
        group = [(x, y, rnd.uniform(0.28, 0.45))]
        for _ in range(rnd.randint(0, 2) if hug else 0):
            a = rnd.uniform(0, 2 * math.pi)
            gx, gy = x + 0.45 * math.cos(a), y + 0.45 * math.sin(a)
            if _d(dj, gx, gy) < -0.15:
                group.append((gx, gy, rnd.uniform(0.15, 0.28)))
        rocks += group
        taken.append(((x, y), 0.8))

    puddles = []
    tries = 0
    while len(puddles) < s["puddles"] and tries < 2000:
        tries += 1
        x, y = rnd.uniform(1, s["W"] - 1), rnd.uniform(1, s["H"] - 1)
        r = (rnd.uniform(0.6, 1.3), rnd.uniform(0.4, 0.9))
        if _d(dj, x, y) < -(max(r) + 0.6) and free(x, y, max(r)):
            puddles.append({"at": (x, y), "r": r, "rot": rnd.uniform(0, math.pi), "deep": False})
            taken.append(((x, y), max(r)))

    stal = []
    tries = 0
    while len(stal) < s["stalagmites"] and tries < 3000:
        tries += 1
        x, y = rnd.uniform(0.5, s["W"] - 0.5), rnd.uniform(0.5, s["H"] - 0.5)
        if -2.2 < _d(dj, x, y) < -0.35 and free(x, y, 0.6):
            stal.append((x, y, rnd.uniform(0.22, 0.4)))
            taken.append(((x, y), 0.5))
    stal += [(f["at"][0], f["at"][1], 0.2 + 0.15 * f["r"]) for f in s["features"] if f["kind"] == "stalagmite"]

    cracks = [list(c) for c in s["crack_paths"]]
    tries = 0
    while len(cracks) < s["crack_paths"].__len__() + s["cracks"] and tries < 500:
        tries += 1
        x, y = rnd.uniform(1, s["W"] - 1), rnd.uniform(1, s["H"] - 1)
        if _d(dj, x, y) > -1.2 or not free(x, y, 1.0):
            continue
        a, pts = rnd.uniform(0, 2 * math.pi), [(x, y)]
        for _ in range(rnd.randint(4, 8)):
            a += rnd.uniform(-0.7, 0.7)
            x, y = x + 0.35 * math.cos(a), y + 0.35 * math.sin(a)
            if _d(dj, x, y) > -0.2:
                break
            pts.append((x, y))
        if len(pts) > 3:
            cracks.append(pts)

    dots = []
    for g in s["glow"]:
        n = 0
        for _ in range(g["n"] * 30):
            if n >= g["n"]:
                break
            a, rr = rnd.uniform(0, 2 * math.pi), g["spread"] * math.sqrt(rnd.random())
            x, y = g["at"][0] + rr * math.cos(a), g["at"][1] + rr * math.sin(a)
            if _d(dj, x, y) < -0.05:
                dots.append((x, y, rnd.uniform(0.07, 0.17), g["color"]))
                n += 1
    bones = []
    for f in s["features"]:
        if f["kind"] in ("bones", "charred"):
            for _ in range(f["n"]):
                a, rr = rnd.uniform(0, 2 * math.pi), f["r"] * math.sqrt(rnd.random())
                bones.append((f["at"][0] + rr * math.cos(a), f["at"][1] + rr * math.sin(a),
                              rnd.uniform(0, math.pi), rnd.uniform(0.25, 0.5), f["kind"] == "charred"))
    return {"rocks": rocks, "puddles": puddles, "dots": dots, "bones": bones, "stal": stal, "cracks": cracks,
            "rnd_seed": rnd.randint(0, 2 ** 31)}


class Pen:
    def __init__(self, img, px):
        self.d = ImageDraw.Draw(img)
        self.px = px
        self.lw = max(1, round(px * 0.028))

    def P(self, x, y):
        return (x * self.px, y * self.px)

    def poly(self, pts, fill, outline=INK, width=None):
        q = [self.P(*p) for p in pts]
        self.d.polygon(q, fill=fill)
        if outline:
            self.d.line(q + [q[0]], fill=outline, width=width or self.lw, joint="curve")

    def circle(self, x, y, r, fill, outline=INK, width=None):
        cx, cy = self.P(x, y)
        R = r * self.px
        self.d.ellipse((cx - R, cy - R, cx + R, cy + R), fill=fill, outline=outline, width=width or self.lw)

    def line(self, pts, fill=INK, width=None):
        self.d.line([self.P(*p) for p in pts], fill=fill, width=width or self.lw, joint="curve")


def frame(at, rot):
    c, s = math.cos(rot), math.sin(rot)
    return lambda u, v: (at[0] + u * c - v * s, at[1] + u * s + v * c)


def blob(rnd, x, y, r, n=9):
    return [(x + r * (0.75 + 0.35 * rnd.random()) * math.cos(2 * math.pi * k / n),
             y + r * (0.75 + 0.35 * rnd.random()) * math.sin(2 * math.pi * k / n)) for k in range(n)]


def draw_rock(pen, rnd, x, y, r):
    pts = blob(rnd, x, y, r)
    pen.poly(pts, STONE)
    pen.poly(blob(rnd, x - r * 0.18, y - r * 0.2, r * 0.45, 7), STONE_LIT, outline=None)


def draw_bedroll(pen, T):
    pen.poly([T(-0.5, -1.05), T(0.5, -1.05), T(0.5, 1.05), T(-0.5, 1.05)], (150, 128, 96, 255))
    pen.poly([T(-0.38, -0.95), T(0.38, -0.95), T(0.38, -0.55), T(-0.38, -0.55)], (178, 160, 128, 255))
    pen.line([T(-0.5, 0.15), T(0.5, 0.25)])


def draw_pack(pen, T):
    pen.poly([T(-0.3, -0.38), T(0.3, -0.38), T(0.34, 0.38), T(-0.34, 0.38)], (112, 84, 58, 255))
    pen.poly([T(-0.3, -0.38), T(0.3, -0.38), T(0.24, -0.05), T(-0.24, -0.05)], (92, 68, 48, 255))


def draw_fire(pen, rnd, T, lit):
    for k in range(9):
        a = 2 * math.pi * k / 9
        x, y = T(0.42 * math.cos(a), 0.42 * math.sin(a))
        draw_rock(pen, rnd, x, y, 0.12)
    for k in range(5):
        a = rnd.uniform(0, math.pi)
        x, y = T(0, 0)
        pen.line([(x - 0.25 * math.cos(a), y - 0.25 * math.sin(a)), (x + 0.25 * math.cos(a), y + 0.25 * math.sin(a))],
                 fill=(70, 46, 32, 255), width=max(2, round(pen.px * 0.06)))
    if lit:
        x, y = T(0, 0)
        pen.circle(x, y, 0.17, (255, 214, 140, 255), outline=(255, 150, 70, 255))


def draw_bone(pen, x, y, a, L, charred=False):
    c, s = math.cos(a) * L / 2, math.sin(a) * L / 2
    col = (58, 50, 46, 255) if charred else (214, 204, 180, 255)
    pen.line([(x - c, y - s), (x + c, y + s)], fill=col, width=max(2, round(pen.px * 0.05)))
    for e in (-1, 1):
        pen.circle(x + e * c, y + e * s, 0.05, (70, 60, 54, 255) if charred else (222, 212, 188, 255), width=1)


def draw_brazier(pen, T, lit):
    for k in range(3):
        a = 2 * math.pi * k / 3 + 0.5
        pen.line([T(0, 0), T(0.42 * math.cos(a), 0.42 * math.sin(a))], fill=IRON, width=max(2, round(pen.px * 0.05)))
    x, y = T(0, 0)
    pen.circle(x, y, 0.3, (60, 58, 62, 255), width=pen.lw + 1)
    pen.circle(x, y, 0.22, (120, 40, 24, 255) if lit else (40, 36, 34, 255), outline=None)
    if lit:
        pen.circle(x, y, 0.13, (255, 190, 90, 255), outline=(255, 120, 50, 255))


STRAW = [(176, 150, 92, 255), (150, 124, 74, 255), (196, 172, 112, 255)]
WOOD = (98, 72, 50, 255)
WOOD_D = (70, 50, 36, 255)
IRON = (70, 70, 74, 255)
FLESH = (128, 108, 94, 255)


def draw_stalagmite(pen, rnd, x, y, r):
    pen.poly(blob(rnd, x + r * 0.25, y + r * 0.3, r * 1.05, 10), (40, 34, 30, 110), outline=None)  # shadow
    pen.poly(blob(rnd, x, y, r, 10), (118, 108, 98, 255))
    pen.poly(blob(rnd, x - r * 0.1, y - r * 0.12, r * 0.62, 8), (142, 132, 120, 255), outline=(60, 52, 46, 200))
    pen.circle(x - r * 0.18, y - r * 0.2, r * 0.22, (176, 168, 156, 255), outline=None)


def draw_crack(pen, rnd, pts):
    pen.line(pts, fill=(40, 31, 27, 220), width=max(1, pen.lw - 1))
    for i in range(1, len(pts) - 1, 2):
        a = rnd.uniform(0, 2 * math.pi)
        x, y = pts[i]
        pen.line([(x, y), (x + 0.25 * math.cos(a), y + 0.25 * math.sin(a))], fill=(40, 31, 27, 170), width=1)


def draw_stairs(pen, st):
    T = frame(st["at"], st["rot"])
    w, l, n = st["w"] / 2, st["l"] / 2, st["n"]
    for k in range(n):  # each step a slightly ragged slab, darker the further down it goes
        v0, v1 = -l + 2 * l * k / n, -l + 2 * l * (k + 1) / n
        tone = int(150 - 60 * (k / max(n - 1, 1) if st["down"] else 1 - k / max(n - 1, 1)))
        j = 0.04 * ((k * 7919) % 5 - 2)
        pen.poly([T(-w, v0 + j), T(w, v0 - j), T(w, v1), T(-w, v1)], (tone, tone - 8, tone - 16, 255))
    pen.line([T(-w, -l), T(-w, l)], width=pen.lw + 1)
    pen.line([T(w, -l), T(w, l)], width=pen.lw + 1)


def draw_nest(pen, rnd, T, r):
    body = [T(r * math.cos(a) * 1.1, r * 0.8 * math.sin(a)) for a in [i * math.pi / 9 for i in range(18)]]
    pen.poly(body, (132, 110, 70, 255))
    for _ in range(int(60 * r)):
        a, rr = rnd.uniform(0, 2 * math.pi), r * math.sqrt(rnd.random())
        u, v = rr * math.cos(a) * 1.05, rr * 0.75 * math.sin(a)
        b = rnd.uniform(0, math.pi)
        pen.line([T(u - 0.14 * math.cos(b), v - 0.14 * math.sin(b)), T(u + 0.14 * math.cos(b), v + 0.14 * math.sin(b))],
                 fill=rnd.choice(STRAW), width=max(1, pen.lw // 2))
    hollow = [T(r * 0.45 * math.cos(a), r * 0.32 * math.sin(a)) for a in [i * math.pi / 8 for i in range(16)]]
    pen.poly(hollow, (96, 78, 52, 200), outline=None)
    fur = [T(r * 0.2 + 0.35 * math.cos(a), -r * 0.1 + 0.25 * math.sin(a)) for a in [i * math.pi / 6 for i in range(12)]]
    pen.poly(fur, (84, 76, 70, 255), outline=(50, 44, 40, 255))


def draw_cage(pen, rnd, T, r):
    h = 0.7 * r
    pen.poly([T(-h, -h), T(h, -h), T(h, h), T(-h, h)], (54, 44, 36, 255), width=pen.lw + 2)
    for k in range(1, 6):  # lid planks with gaps
        u = -h + 2 * h * k / 6
        pen.line([T(u, -h), T(u, h)], fill=WOOD, width=max(2, round(pen.px * 0.09)))
    pen.line([T(-h, -h * 0.6), T(h, -h * 0.6)], fill=WOOD_D, width=max(2, round(pen.px * 0.07)))
    pen.line([T(-h, h * 0.6), T(h, h * 0.6)], fill=WOOD_D, width=max(2, round(pen.px * 0.07)))
    x, y = T(0.1, 0)
    draw_rock(pen, rnd, x, y, 0.32 * r)


def draw_chain(pen, a, b):
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.12))
    for k in range(n):
        t = (k + 0.5) / n
        x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        pen.circle(x, y, 0.045, None, outline=IRON, width=max(1, pen.lw // 2))


def draw_corpse(pen, T, chained):
    for (u0, v0, u1, v1) in ((-0.15, 0.35, -0.2, 0.95), (0.15, 0.35, 0.22, 0.95), (-0.2, -0.25, -0.62, -0.62),
                             (0.2, -0.25, 0.62, -0.62)):
        pen.line([T(u0, v0), T(u1, v1)], fill=FLESH, width=max(2, round(pen.px * 0.1)))
    pen.poly([T(0.24 * math.cos(a), 0.42 * math.sin(a)) for a in [i * math.pi / 8 for i in range(16)]], (96, 84, 76, 255))
    x, y = T(0, -0.55)
    pen.circle(x, y, 0.15, FLESH)
    if chained:
        for e in (-1, 1):
            draw_chain(pen, T(e * 0.62, -0.62), T(e * 0.7, -1.05))


def draw_statue(pen, rnd, T, r):
    pen.poly([T(-0.75 * r, -0.6 * r), T(0.75 * r, -0.6 * r), T(0.75 * r, 0.6 * r), T(-0.75 * r, 0.6 * r)], (92, 70, 50, 255))
    pen.poly([T(0.55 * r * math.cos(a), 0.32 * r * math.sin(a)) for a in [i * math.pi / 8 for i in range(16)]], (120, 88, 60, 255))
    x, y = T(0, -0.05 * r)
    pen.circle(x, y, 0.2 * r, (112, 82, 56, 255))
    for e in (-1, 1):  # ears: the wolf-headed figure reads from above
        pen.poly([T(e * 0.08 * r, -0.2 * r), T(e * 0.22 * r, -0.36 * r), T(e * 0.2 * r, -0.12 * r)], (96, 70, 48, 255))
    pen.poly([T(-0.08 * r, 0.12 * r), T(0.08 * r, 0.12 * r), T(0, 0.34 * r)], (104, 76, 52, 255))
    for k in range(14):  # a garland of pale night flowers
        a = 2 * math.pi * k / 14
        x, y = T(0.5 * r * math.cos(a), 0.3 * r * math.sin(a))
        pen.circle(x, y, 0.05 * r, rnd.choice([(214, 206, 226, 255), (186, 170, 214, 255), (120, 140, 96, 255)]), width=1)


def draw_treasure(pen, rnd, T, r):
    # the mound first: a heap of dull gold, lit on its upper side, then the coins and gems on top
    pen.poly([T(r * 1.05 * math.cos(a) * (0.9 + 0.2 * rnd.random()), r * 0.75 * math.sin(a) * (0.9 + 0.2 * rnd.random()))
              for a in [i * math.pi / 12 for i in range(24)]], (150, 116, 46, 255), outline=(90, 66, 26, 255))
    pen.poly([T(r * 0.6 * math.cos(a) - 0.15 * r, r * 0.42 * math.sin(a) - 0.12 * r) for a in [i * math.pi / 10 for i in range(20)]],
             (196, 160, 70, 255), outline=None)
    for _ in range(int(70 * r * r)):
        a, rr = rnd.uniform(0, 2 * math.pi), r * math.sqrt(rnd.random())
        x, y = T(rr * math.cos(a), rr * 0.7 * math.sin(a))
        c = rnd.choice([(222, 182, 72, 255), (238, 206, 104, 255), (196, 160, 60, 255), (200, 200, 206, 255)])
        if rnd.random() < 0.06:
            c = rnd.choice([(170, 40, 50, 255), (60, 110, 180, 255), (70, 150, 90, 255)])
        pen.circle(x, y, rnd.uniform(0.05, 0.09), c, outline=(90, 70, 30, 255), width=1)


def draw_torch(pen, T):
    pen.poly([T(-0.12, -0.18), T(0.12, -0.18), T(0.08, 0.2), T(-0.08, 0.2)], IRON)
    x, y = T(0, -0.05)
    pen.circle(x, y, 0.16, (255, 196, 96, 255), outline=(220, 120, 50, 255))
    pen.circle(x, y, 0.07, (255, 240, 190, 255), outline=None)


def draw_claws(pen, T, r):
    for e in (-1, 0, 1):
        pen.line([T(e * 0.14, -0.45 * r), T(e * 0.14 + 0.08, 0.45 * r)], fill=(30, 24, 22, 230), width=max(1, pen.lw - 1))


def draw_paw(pen, x, y, a, s=0.13):
    c, si = math.cos(a), math.sin(a)
    P = lambda u, v: (x + u * c - v * si, y + u * si + v * c)  # noqa: E731
    col = (60, 46, 38, 200)
    pen.circle(*P(0, 0), s * 0.55, col, outline=None)
    for u, v in ((0.75, -0.55), (0.95, -0.18), (0.95, 0.18), (0.75, 0.55)):
        pen.circle(*P(u * s, v * s), s * 0.22, col, outline=None)


def draw_tracks(pen, a, b):
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    n = max(2, int(L / 0.45))
    for k in range(n):
        t = k / (n - 1)
        side = 0.13 if k % 2 else -0.13
        x = a[0] + (b[0] - a[0]) * t - side * math.sin(ang)
        y = a[1] + (b[1] - a[1]) * t + side * math.cos(ang)
        draw_paw(pen, x, y, ang)


def draw_web(pen, T, r):
    col = (210, 210, 214, 150)
    for k in range(6):
        a = -0.2 + k * (math.pi / 2 + 0.4) / 5
        pen.line([T(0, 0), T(r * math.cos(a), r * math.sin(a))], fill=col, width=1)
    for ring in (0.35, 0.6, 0.85):
        pts = [T(ring * r * math.cos(-0.2 + k * (math.pi / 2 + 0.4) / 5), ring * r * math.sin(-0.2 + k * (math.pi / 2 + 0.4) / 5)) for k in range(6)]
        pen.line(pts, fill=col, width=1)


def draw_roots(pen, rnd, T, r):
    for _ in range(3):
        u, v, a = 0.0, rnd.uniform(-0.3, 0.3), rnd.uniform(-0.4, 0.4)
        pts = [T(u, v)]
        while u < r:
            a += rnd.uniform(-0.5, 0.5)
            u, v = u + 0.2 * math.cos(a), v + 0.2 * math.sin(a)
            pts.append(T(u, v))
        pen.line(pts, fill=(84, 64, 46, 255), width=max(2, round(pen.px * 0.05)))


def draw_moss(pen, rnd, x, y, r):
    for _ in range(int(80 * r * r)):
        a, rr = rnd.uniform(0, 2 * math.pi), r * math.sqrt(rnd.random())
        pen.circle(x + rr * math.cos(a), y + rr * math.sin(a), rnd.uniform(0.03, 0.08),
                   rnd.choice([(72, 96, 60, 170), (92, 116, 70, 150), (58, 80, 52, 180)]), outline=None)


def draw_skull(pen, T):
    pen.poly([T(0.16 * math.cos(a), 0.2 * math.sin(a)) for a in [i * math.pi / 6 for i in range(12)]], (222, 212, 188, 255))
    for e in (-1, 1):
        x, y = T(e * 0.06, -0.02)
        pen.circle(x, y, 0.04, (40, 31, 27, 255), outline=None)


def draw_spear(pen, T, r):
    pen.line([T(-r, 0), T(r, 0)], fill=WOOD, width=max(2, round(pen.px * 0.05)))
    pen.poly([T(r, -0.07), T(r + 0.3, 0), T(r, 0.07)], (150, 150, 156, 255))


def draw_carcass(pen, rnd, T, r):
    """A large stripped beast: splayed legs, a hide torn open on a red ribcage, the head with antlers."""
    for e, (u, v) in ((-1, (-0.9, 0.35)), (1, (-0.9, -0.35)), (-1, (0.8, 0.4)), (1, (0.8, -0.4))):
        pen.line([T(u * r, v * r), T((u + 0.25) * r, e * 1.05 * r)], fill=(88, 62, 46, 255), width=max(3, round(pen.px * 0.11 * r)))
    hide = [T(r * 1.25 * math.cos(a) * (0.9 + 0.15 * rnd.random()), r * 0.62 * math.sin(a) * (0.9 + 0.15 * rnd.random()))
            for a in [i * math.pi / 10 for i in range(20)]]
    pen.poly(hide, (104, 72, 54, 255))
    pen.poly([T(r * 0.8 * math.cos(a), r * 0.36 * math.sin(a)) for a in [i * math.pi / 10 for i in range(20)]],
             (132, 40, 34, 255), outline=(70, 24, 20, 255))
    pen.line([T(-0.75 * r, 0), T(0.75 * r, 0)], fill=(224, 214, 192, 255), width=max(2, round(pen.px * 0.06 * r)))
    for i in range(-4, 5):
        u = i * 0.16 * r
        for e in (-1, 1):
            pen.line([T(u, 0), T(u + 0.05 * r, e * 0.3 * r), T(u - 0.02 * r, e * 0.36 * r)],
                     fill=(226, 216, 194, 255), width=max(1, round(pen.px * 0.035 * r)))
    hx, hy = 1.55 * r, 0
    pen.line([T(1.1 * r, 0), T(hx, hy)], fill=(96, 66, 50, 255), width=max(3, round(pen.px * 0.16 * r)))
    pen.poly([T(hx + 0.42 * r * math.cos(a), 0.18 * r * math.sin(a)) for a in [i * math.pi / 6 for i in range(12)]],
             (110, 78, 58, 255))
    for e in (-1, 1):  # antlers
        pts = [T(hx - 0.05 * r, e * 0.1 * r), T(hx - 0.2 * r, e * 0.55 * r), T(hx - 0.55 * r, e * 0.85 * r)]
        pen.line(pts, fill=(200, 186, 160, 255), width=max(2, round(pen.px * 0.05 * r)))
        for k in (0.35, 0.6):
            x, y = T(hx - 0.2 * r - k * 0.35 * r, e * (0.55 + k * 0.3) * r)
            x2, y2 = T(hx + 0.05 * r - k * 0.3 * r, e * (0.75 + k * 0.3) * r)
            pen.line([(x, y), (x2, y2)], fill=(200, 186, 160, 255), width=max(2, round(pen.px * 0.04 * r)))


def draw(s, placed, px, size):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    pen = Pen(img, px)
    rnd = random.Random(placed["rnd_seed"])
    for pts in placed["cracks"]:
        draw_crack(pen, rnd, pts)
    for st in s["stairs"]:
        draw_stairs(pen, st)
    for f in s["features"]:
        if f["kind"] == "moss":
            draw_moss(pen, rnd, f["at"][0], f["at"][1], f["r"])
    for x, y, r in placed["rocks"]:
        draw_rock(pen, rnd, x, y, r)
    for x, y, r in placed["stal"]:
        draw_stalagmite(pen, rnd, x, y, r)
    for f in s["features"]:
        T = frame(f["at"], f["rot"])
        k = f["kind"]
        if k == "camp":
            draw_bedroll(pen, T)
            draw_pack(pen, frame(T(-1.0, -0.6), f["rot"] + 0.2))
            draw_fire(pen, rnd, frame(T(1.6, 0), 0), f["lit"])
        elif k == "bedroll":
            draw_bedroll(pen, T)
        elif k == "pack":
            draw_pack(pen, T)
        elif k == "fire":
            draw_fire(pen, rnd, T, f["lit"])
        elif k == "crate":
            pen.poly([T(-0.45, -0.45), T(0.45, -0.45), T(0.45, 0.45), T(-0.45, 0.45)], (122, 94, 64, 255))
            pen.line([T(-0.45, -0.45), T(0.45, 0.45)])
        elif k == "altar":
            pen.poly([T(-1.0, -0.55), T(1.0, -0.55), T(1.0, 0.55), T(-1.0, 0.55)], (104, 98, 94, 255))
            pen.poly([T(-0.8, -0.38), T(0.8, -0.38), T(0.8, 0.38), T(-0.8, 0.38)], (122, 116, 110, 255))
        elif k == "carcass":
            draw_carcass(pen, rnd, T, f["r"])
        elif k == "nest":
            draw_nest(pen, rnd, T, f["r"])
        elif k == "cage":
            draw_cage(pen, rnd, T, f["r"])
        elif k == "corpse":
            draw_corpse(pen, T, f["chained"])
        elif k == "chains":
            draw_chain(pen, f["at"], f["to"] or T(0, -1))
        elif k == "statue":
            draw_statue(pen, rnd, T, f["r"])
        elif k == "treasure":
            draw_treasure(pen, rnd, T, f["r"])
        elif k == "torch":
            draw_torch(pen, T)
        elif k == "claws":
            draw_claws(pen, T, f["r"])
        elif k == "tracks":
            draw_tracks(pen, f["at"], f["to"] or T(3, 0))
        elif k == "web":
            draw_web(pen, T, f["r"])
        elif k == "roots":
            draw_roots(pen, rnd, T, f["r"])
        elif k == "skull":
            draw_skull(pen, T)
        elif k == "brazier":
            draw_brazier(pen, T, f["lit"])
        elif k == "spear":
            draw_spear(pen, T, f["r"])
    for x, y, a, L, ch in placed["bones"]:
        draw_bone(pen, x, y, a, L, ch)
    for x, y, r, col in placed["dots"]:
        c = GLOW_COLOURS[col]
        pen.circle(x, y, r, (*c, 255), outline=(*[v // 3 for v in c], 255), width=max(1, pen.lw // 2))
        pen.circle(x - r * 0.3, y - r * 0.3, r * 0.35, (255, 255, 240, 200), outline=None)
    return img.filter(ImageFilter.GaussianBlur(max(0.4, px / 160)))
