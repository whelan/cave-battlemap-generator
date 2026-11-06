"""Asset index over every Dungeondraft pack in the custom assets folder, plus image access.

CLI:
  python3 ddassets.py index                 rebuild the cache (otherwise built on first use)
  python3 ddassets.py find REGEX [REGEX..]  matching textures with pixel size (LIM=n for more hits)
  python3 ddassets.py sheet OUT.png REGEX [N]   contact sheet of up to N matches, numbered
  python3 ddassets.py catalog [DIR]         write the compact per-theme catalog (default: ../catalog)
"""
import io, json, os, re, struct, sys

DD_CONFIG = os.path.expanduser("~/Library/Application Support/Dungeondraft/config.ini")
CACHE = os.path.expanduser("~/.cache/cave-battlemap-generator/dd-index.json")


def _config(key):
    try:
        m = re.search(rf'^{key}=(.*)$', open(DD_CONFIG).read(), re.M)
        return m.group(1).strip() if m else None
    except OSError:
        return None


def assets_dir():
    d = os.environ.get("DDMAP_ASSETS") or (_config("custom_assets_directory") or "").strip('"')
    if not d or not os.path.isdir(d):
        raise SystemExit("No Dungeondraft custom assets folder: set DDMAP_ASSETS or Dungeondraft's custom_assets_directory")
    return d


def active_packs():
    """Pack ids Dungeondraft had enabled when it last saved its config (it writes this on quit)."""
    return re.findall(r'"([^"]+)"', _config("active_asset_packs") or "")


def read_pck(path):
    """(entries, pack meta) of a Godot .pck / .dungeondraft_pack: entries are (res path, offset, size)."""
    with open(path, "rb") as f:
        if f.read(4) != b"GDPC":
            return [], None
        f.read(80)
        (n,) = struct.unpack("<I", f.read(4))
        entries = []
        for _ in range(n):
            (ln,) = struct.unpack("<I", f.read(4))
            name = f.read(ln).rstrip(b"\0").decode("utf-8", "replace")
            off, size = struct.unpack("<QQ", f.read(16))
            f.read(16)
            entries.append((name, off, size))
        meta = None
        for name, off, size in entries:
            if name.startswith("res://packs/") and name.endswith(".json") and name.count("/") == 3:
                f.seek(off)
                meta = json.loads(f.read(size).decode("utf-8", "replace"))
                break
    return entries, meta


def _version(v):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", str(v)))


def build_index():
    root = assets_dir()
    found = {}
    for dp, _, fs in os.walk(root):
        for fn in fs:
            if fn.endswith(".dungeondraft_pack"):
                p = os.path.join(dp, fn)
                entries, meta = read_pck(p)
                if not meta:
                    continue
                old = found.get(meta["id"])  # the same pack twice (an old version left beside the new): keep the newest
                if not old or _version(meta.get("version")) > _version(old[1].get("version")):
                    found[meta["id"]] = (p, meta, entries)
    # Forgotten Adventures first: a pattern that could match both never lands on a third-party asset by accident
    order = sorted(found, key=lambda i: (found[i][1].get("author") != "Forgotten Adventures", found[i][1]["name"]))
    assets = {}
    for pid in order:
        p, meta, entries = found[pid]
        for name, off, size in entries:
            assets.setdefault(name, [p, off, size])
    idx = {"root": root, "packs": [{"path": found[i][0], "meta": found[i][1]} for i in order], "assets": assets,
           "mtimes": {found[i][0]: os.path.getmtime(found[i][0]) for i in order}}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(idx, open(CACHE, "w"))
    return idx


_IDX = None


def index():
    global _IDX
    if _IDX is None:
        try:
            _IDX = json.load(open(CACHE))
            stale = any(not os.path.exists(p) or os.path.getmtime(p) != t for p, t in _IDX["mtimes"].items())
            if stale:
                _IDX = build_index()
        except (OSError, ValueError, KeyError):
            _IDX = build_index()
        _IDX["keys"] = [k for k in _IDX["assets"] if "/textures/" in k]
    return _IDX


def pack_meta(pid):
    return next((p["meta"] for p in index()["packs"] if p["meta"]["id"] == pid), None)


_picks = {}


def pick(pat, missing=None):
    """The first texture (FA packs first) whose res path matches the regex. `missing` collects misses instead of failing."""
    if pat not in _picks:
        _picks[pat] = next((k for k in index()["keys"] if re.search(pat, k)), None)
    if _picks[pat] is None:
        if missing is not None:
            missing.append(pat)
            return "res://missing/" + pat
        raise SystemExit(f"no asset matches {pat!r}  (try: python3 ddassets.py find {pat!r})")
    return _picks[pat]


def pick_first(*pats, missing=None):
    for p in pats[:-1]:
        hit = next((k for k in index()["keys"] if re.search(p, k)), None)
        if hit:
            return hit
    return pick(pats[-1], missing)


def raw(res):
    e = index()["assets"].get(res)
    if not e:
        return None
    with open(e[0], "rb") as f:
        f.seek(e[1])
        return f.read(e[2])


def dims(res):
    """Pixel size from the image header, without decoding."""
    b = (raw(res) or b"")[:64]
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", b[16:24])
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        c = b[12:16]
        if c == b"VP8 ":
            w, h = struct.unpack("<HH", b[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if c == b"VP8L":
            v = int.from_bytes(b[21:25], "little")
            return (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1
        if c == b"VP8X":
            return int.from_bytes(b[24:27], "little") + 1, int.from_bytes(b[27:30], "little") + 1
    im = img(res)
    return im.size if im else None


_imgs = {}


def img(res):
    if res not in _imgs:
        from PIL import Image
        b = raw(res)
        _imgs[res] = Image.open(io.BytesIO(b)).convert("RGBA") if b else None
    return _imgs[res]


def sheet(out, pat, limit=30, cell=160):
    import math
    from PIL import Image, ImageDraw
    keys = [k for k in index()["keys"] if re.search(pat, k) and re.search(r"\.(webp|png|jpg)$", k)][:limit]
    cols = 6
    im = Image.new("RGB", (cols * cell, max(1, math.ceil(len(keys) / cols)) * (cell + 14)), (60, 60, 60))
    d = ImageDraw.Draw(im)
    for i, k in enumerate(keys):
        t = img(k)
        x, y = (i % cols) * cell, (i // cols) * (cell + 14)
        if t:
            t = t.copy(); t.thumbnail((cell - 4, cell - 4)); im.paste(t, (x + 2, y + 2), t)
        d.text((x + 2, y + cell), f"{i}:{k.rsplit('/', 1)[1][:cell // 6]}", fill=(255, 255, 0))
        print(i, k.replace("res://packs/", ""))
    im.save(out)


# ---- the committed catalog: what exists, readable without the packs (cloud sessions) ----

IMG = re.compile(r"\.(webp|png|jpe?g)$", re.I)
GRID = re.compile(r"^\d+x\d+$")
FA_VARIANT = re.compile(r"^([A-Z]\d*[A-Z]?|\d+[A-Z]?)$")
COLORABLE = re.compile(r"^(colou?rable|clr)$", re.I)
# brace sets that recur hundreds of times get a short name; the legend in INDEX.md spells them out
ALIASES = {"Ashen,Dark,Light": "wood3", "Black,Blue,Brown,Green,Purple,Red,Yellow": "cloth7",
           "Earthy,Sandstone,Slate": "stone3", "Earthy,Redrock,Sandstone,Slate,Volcanic": "stone5",
           "Connector,Corner,Ending,Joint,Straight": "cliff5"}
# theme file <- first rule whose regex matches the asset's folder (objects) or kind (other resources)
THEMES = [   # matched against the folder with "_" read as a space, so \b works on FA names
    ("textures", "floors, terrain, walls, paths, doors/portals, roof styles, light shapes (non-object resources)", r"^(?!objects/)"),
    ("death", "burial, graves, coffins, tombs, bones, corpses, gore, blood", r"burial|grave|gore|\bbones?\b|blood|skelet|corps|coffin|cemetery|funeral|tomb|crypt"),
    ("lights-fx", "light sources, fire, smoke, fog, magic and overlay effects", r"lightsource|\blighting\b|candle|lantern|torch|aoa |\bfire\b|smoke|electric|plasma|overlay|effects|magic clouds|magic symbols|spells|\bfog\b|\bvoid\b|runes|eye overlays"),
    ("furniture", "beds, tables, seating, storage furniture, shelves, counters, hearths, altars", r"furniture|seating|bedding|\bbeds\b|tables|\bbars\b|counters|shelves|wardrobe|cupboard|desks|fireplace|book stands|toilets|washing|cooking appliances|room dividers|altars|workbench|displays|merchants|weapon racks"),
    ("work", "workshops, farm and craft gear, combat, weapons, armour, vehicles, tools, machines", r"workplace|combat|weapon|armou?r|vehicle|\bcarts?\b|boat|shipwreck|\btools\b|machine|siege|\bcraft\b|horse equipment|trains|sails|cogs"),
    ("structures", "building parts: walls, doors, stairs, beams, pillars, fences, roofs, chimneys, statues, wells, prefab buildings, bridges, tents, ruins", r"structur|\broofs?\b|building|modular|bridge|\bwalls?\b|\bdoors?\b|stair|pillar|fence|railing|palisade|\btents?\b|tc floors|\bfloors\b|platforms|planks|beams|windows|wells|\bpipes\b|barricades|retaining|chimney|ruins|statues|fountains|archeology|decks and docks|shelters?\b"),
    ("nature", "flora, trees, rocks, cliffs, water, animals, mushrooms, snow and ice", r"flora|natural|\brocks?\b|\btrees?\b|plants|flower|mushroom|fung|animal|terrain|cliff|water|lava|snow|frozen|\bice\b|cloud|crystal|mineral|creature|eggs|nests|webs|\bcrops\b|gardens|\bpools?\b|ponds|potted|\bwood\b"),
    ("clutter", "everything small: decor, food, drink, books, papers, containers, cloth, rugs, curtains, tableware, treasure", r""),
]


def _tag(meta):
    n = meta["name"]
    return "FA" if n.startswith("FA_") else "FAc" if n.startswith("[FA") else re.split(r"[ _]", n)[0]


def _short(folder):
    parts = [re.sub(r"^(\[WFW\] |\[FA Com\.\] |TC |_LG_)", "", p) for p in folder.split("/")]
    drop = {"Anniversary Megapack", "Fantasy", "Artificial Assets", "Natural Assets", "Prefab Assets", "Modular Assets"}
    return "/".join(p for p in parts if p not in drop) or folder


def _vals(vs):
    """A brace set, numbered runs collapsed: {01-12}, {Patch01-08,Spot01-04}."""
    vs = sorted(vs, key=lambda v: (len(v), v) if v.isdigit() else (99, v))
    key = ",".join(vs)
    if key in ALIASES:
        return "{" + ALIASES[key] + "}"
    runs, out = {}, []
    for v in vs:
        m = re.match(r"^(.*?)(\d+)$", v)
        if m:
            runs.setdefault(m.group(1), []).append(m.group(2))
        else:
            out.append(v)
    for pre, nums in runs.items():
        nums.sort(key=int)
        if len(nums) < 3:
            out += [pre + n for n in nums]
            continue
        start = prev = nums[0]
        spans = []
        for n in nums[1:] + [None]:
            if n is not None and int(n) == int(prev) + 1:
                prev = n
                continue
            spans.append(start if start == prev else f"{start}-{prev}")
            start = prev = n
        out.append(pre + ",".join(spans) if len(spans) == 1 else pre + "(" + ",".join(spans) + ")")
    return "{" + ",".join(out) + "}"


def _lines(files, fa):
    """Collapse a folder's files into lines. Each line is a full product of its brace sets: every
    combination exists. FA variant letters (A, B2) are dropped (a regex lands on the first);
    other packs keep their numbers, since their names are matched exactly."""
    items = {}
    for fn in files:
        toks = [t for t in re.split(r"[_ ]+", IMG.sub("", fn)) if t]
        grid = next((t for t in toks if GRID.match(t)), "")
        base = ["*" if fa and FA_VARIANT.match(t) else t for t in toks if not GRID.match(t) and not COLORABLE.match(t)]
        while base and base[-1] == "*":   # a trailing variant letter is dropped; one mid-name stays as *
            base.pop()
        if base and base[0] == "TC":
            base = base[1:]
        v = items.setdefault(tuple(base) or ("?",), [0, set(), False, " " if " " in fn else "_"])
        v[0] += 1
        v[2] |= any(COLORABLE.match(t) for t in toks)
        if grid:
            v[1].add(grid)
    rows = [[tuple(frozenset([t]) for t in k), v] for k, v in items.items()]
    while True:   # merge the biggest group of rows that differ in one position only
        groups = {}
        for r in rows:
            k = r[0]
            for i in range(len(k)):
                groups.setdefault((len(k), i, k[:i] + k[i + 1:]), []).append(r)
        best = max(groups.items(), key=lambda g: len(g[1]), default=None)
        if not best or len(best[1]) < 2:
            break
        (_, i, _), rs = best
        k = rs[0][0]
        merged = [k[:i] + (frozenset().union(*(r[0][i] for r in rs)),) + k[i + 1:],
                  [sum(r[1][0] for r in rs), set().union(*(r[1][1] for r in rs)), any(r[1][2] for r in rs), rs[0][1][3]]]
        ids = {id(r) for r in rs}
        rows = [r for r in rows if id(r) not in ids] + [merged]
    out = []
    for k, (n, grids, col, sep) in rows:
        name = sep.join(next(iter(s)) if len(s) == 1 else _vals(s) for s in k)
        out.append(name + (" " + ",".join(sorted(grids)) if grids else "") + (f" ×{n}" if n > 1 else "") + (" c" if col else ""))
    return sorted(out, key=str.lower)


def catalog(outdir):
    idx = index()
    meta = {p["meta"]["id"]: p["meta"] for p in idx["packs"]}
    folders = {}
    for k in idx["keys"]:
        if not IMG.search(k):
            continue
        p = k.split("/")
        i = p.index("textures")
        folder = "/".join(p[i + 1:-1])
        folders.setdefault((folder, p[3]), []).append(p[-1])
    themes = {t[0]: [] for t in THEMES}
    counts = {t[0]: [0, 0] for t in THEMES}
    for (folder, pid), files in sorted(folders.items(), key=lambda f: (_tag(meta[f[0][1]]) != "FA", f[0][0].lower())):
        theme = next(t for t, _, rx in THEMES if re.search(rx, folder.replace("_", " "), re.I))
        fa = _tag(meta[pid]) == "FA"
        lines = _lines(files, fa)
        head = _short(folder[8:]) if folder.startswith("objects/") else _short(folder)
        themes[theme].append(f"## {head} [{_tag(meta[pid])}]")
        themes[theme] += lines
        counts[theme][0] += len(files)
        counts[theme][1] += len(lines)
    os.makedirs(outdir, exist_ok=True)
    for t, desc, _ in THEMES:
        open(os.path.join(outdir, f"{t}.md"), "w").write(
            f"# {t}: {desc}\n\nGenerated by `ddassets.py catalog`; the legend is in INDEX.md. "
            f"{counts[t][0]} files in {counts[t][1]} lines.\n\n" + "\n".join(themes[t]) + "\n")
    packs = "\n".join(f"| {_tag(m)} | {m['name']} | `{m['id']}` |" for m in meta.values())
    rows = "\n".join(f"| [{t}.md]({t}.md) | {desc} | {counts[t][1]} | {counts[t][0]} |" for t, desc, _ in THEMES)
    legend = "\n".join(f"- `{{{a}}}` = {{{s}}}" for s, a in ALIASES.items())
    open(os.path.join(outdir, "INDEX.md"), "w").write(f"""# Dungeondraft asset catalog

Generated by `python -m cavemap.ddassets catalog` from every pack in Dungeondraft's custom
assets folder. Do not edit by hand: rerun it when packs change. It lets a session without the
packs (cloud) know what exists and write regexes for `obj()`/`fit()`.

**Don't read a theme file whole** (they run 20–100 KB). `grep -n '^## ' catalog/<theme>.md`
gives its folder map; `grep -i 'chair' catalog/furniture.md` finds lines. A folder can sit in
two themes, so when a theme comes up empty, `grep -ril` the whole folder. Curated favourites
and known traps are in dressing.md, not here.

## Reading a line

`Chair_Wood_{{wood3}} 1x1 ×24 c` under `## Furniture/Seating/Chairs [FA]`:
- the name with **brace sets**: every combination exists (Chair_Wood_Ashen, …_Dark, …_Light);
- the **grid footprint** in 5 ft cells, from the file name (FA draws 256 px a cell, TC 300 px);
- `×24` files in total (variant letters A, B2 … and colour twins), `c` = a colorable twin exists;
- numbered runs: `{{01-12}}`, `{{Patch01-08,Spot1-4}}`, `Fire(02-03,05-18)` with gaps.

**Anchor the name with `/`**: `Chair_Wood_Dark_` lands on `Armchair_Wood_Dark_…`, while
`/Chair_Wood_Dark_` lands on the chair. FA names drop the variant letter, so that regex takes
the first variant (A). A `*` marks a variant letter in mid-name: `Bottle_Glass_*_{{Black,…}}` is
`Bottle_Glass_A_Red_1x1`, matched as `/Bottle_Glass_._Red`. **Other packs** keep their numbers, and their separators as the files have them: the TC file for
`Fur Blanket {{01,02}} 2x1` is `TC_Fur Blanket 01_2x1.webp`, matched as `/TC_Fur Blanket 01_2x1\\.`
(else the `_clr` twin can win). FA packs are searched first by `obj()`.

## Aliases

{legend}

## Themes

| File | Holds | Lines | Files |
|---|---|---|---|
{rows}

## Packs

| Tag | Pack | Id |
|---|---|---|
{packs}
""")
    return counts


if __name__ == "__main__":
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd == "index":
        i = build_index()
        print(len(i["assets"]), "files in", len(i["packs"]), "packs:", ", ".join(p["meta"]["name"] for p in i["packs"]))
    elif cmd == "find":
        lim = int(os.environ.get("LIM", 8))
        for pat in args:
            hits = [k for k in index()["keys"] if re.search(pat, k, re.I)]
            print(f"## {pat} ({len(hits)})")
            for k in hits[:lim]:
                print("  ", k.replace("res://packs/", ""), dims(k))
    elif cmd == "catalog":
        out = args[0] if args else "catalog"
        for t, (f, l) in catalog(out).items():
            print(f"{t}: {f} files, {l} lines")
    elif cmd == "sheet":
        sheet(args[0], args[1], int(args[2]) if len(args) > 2 else 30)
    else:
        print(__doc__)
