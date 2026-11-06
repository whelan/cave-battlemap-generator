"""A minimal .dungeondraft_map writer: the pieces of a Dungeondraft map a cave needs.

Coordinates in cells (1 cell = 5 ft = 256 px in Dungeondraft). Asset patterns are regexes over the
pack index built by `ddassets` from Dungeondraft's custom assets folder.
"""
import datetime
import json
import math
import re
from pathlib import Path

from . import ddassets as A

C = 256  # Dungeondraft px per grid cell
TEMPLATE = Path(__file__).with_name("dd_template.json")


class Writer:
    def __init__(self, W, H, check=False):
        self.W, self.H = W, H
        self.missing = [] if check else None
        self.warnings = []
        self.levels = {}
        self._node = 0x10

    def nid(self):
        self._node += 1
        return format(self._node, "x")

    def pick(self, pat):
        return A.pick(pat, self.missing)

    @staticmethod
    def v2(x, y):
        return f"Vector2( {round(x, 3)}, {round(y, 3)} )"

    @staticmethod
    def pva(pts):
        return "PoolVector2Array( " + ", ".join(f"{round(a, 3)}" for p in pts for a in p) + " )"

    def obj(self, pat, x, y, rot=0, scale=1.0, layer=100):
        sx, sy = scale if isinstance(scale, tuple) else (scale, scale)
        return {"position": self.v2(x * C, y * C), "rotation": round(math.radians(rot), 6), "scale": self.v2(sx, sy),
                "mirror": False, "texture": self.pick(pat), "layer": layer, "shadow": True, "node_id": self.nid()}

    def fit(self, pat, x, y, rot=0, cells=1.0, layer=300):
        """Scale so the image's longest side spans `cells` cells; `cells` as (across, along) stretches each axis."""
        o = self.obj(pat, x, y, rot, 1, layer)
        dm = A.dims(o["texture"]) if not o["texture"].startswith("res://missing/") else None
        if not dm:
            return o
        if isinstance(cells, tuple):
            o["scale"] = self.v2(round(cells[0] * C / dm[0], 4), round(cells[1] * C / dm[1], 4))
        else:
            s = round(cells * C / max(dm), 4)
            o["scale"] = self.v2(s, s)
        return o

    def light(self, x, y, rng, intensity, color):
        return {"position": self.v2(x * C, y * C), "rotation": 0, "range": rng, "intensity": intensity,
                "color": color, "texture": "res://textures/lights/soft.png", "shadows": True, "node_id": self.nid()}

    def fence(self, points, tex, width=64):
        """A path (a texture drawn along a polyline)."""
        (x0, y0), rest = points[0], points[1:]
        return {"position": self.v2(x0 * C, y0 * C), "rotation": 0, "scale": self.v2(1, 1),
                "edit_points": self.pva([(0, 0)] + [((x - x0) * C, (y - y0) * C) for x, y in rest]),
                "smoothness": 0, "texture": tex, "width": width, "layer": 100, "fade_in": False, "fade_out": False,
                "grow": False, "shrink": False, "loop": False, "node_id": self.nid()}

    def manifest(self):
        used = set()
        for lv in self.levels.values():
            used.update(re.findall(r"res://packs/([^/]+)/", json.dumps(lv)))
        return [m for m in (A.pack_meta(p) for p in sorted(used)) if m]

    def write(self, out, open_level=0):
        tmpl = json.loads(TEMPLATE.read_text())
        now = datetime.datetime.now()
        header = tmpl["header"]
        header["creation_date"] = {"year": now.year, "month": now.month, "day": now.day, "weekday": (now.weekday() + 1) % 7,
                                   "dst": False, "hour": now.hour, "minute": now.minute, "second": now.second}
        header["uses_default_assets"] = True
        header["asset_manifest"] = self.manifest()
        header["editor_state"]["camera_position"] = self.v2(self.W * C / 2, self.H * C / 2)
        header["editor_state"]["current_level"] = open_level
        world = tmpl["world"]
        world.update({"width": self.W, "height": self.H, "next_node_id": self.nid(), "levels": self.levels})
        Path(out).write_text(json.dumps({"header": header, "world": world, "mod": {".node_table": {}}}, indent="\t"))
        active = A.active_packs()
        inactive = [m["name"] for m in header["asset_manifest"] if active and m["id"] not in active]
        if inactive:
            self.warnings.append("packs used but not enabled in Dungeondraft (enable them under Assets): " + ", ".join(inactive))
