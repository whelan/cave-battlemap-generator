# Spec reference

A spec is one JSON object. All positions and sizes are in **grid cells** (1 cell = 5 ft = 70 px by default). `[x, y]` is measured from the top-left corner; y grows downward. Angles (`rot`) are degrees, clockwise.

## Top level

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | `"Cave"` | Map title; used in QA output and file metadata. |
| `size` | `[w, h]` | required | Map size in cells. |
| `seed` | integer | `1` | Random seed; same spec + seed gives the same drawing. |
| `chambers` | array | required | Elliptical rooms. The first one is the entrance; all others must connect to it. |
| `passages` | array | `[]` | Tunnels between chambers, points or map edges. |
| `pillars` | array | `[]` | Rock islands inside the floor. |
| `pools` | array | `[]` | Water drawn on the floor. |
| `features` | array | `[]` | Assets placed on the map. |
| `roughness` | number | `1` | Wall jaggedness (0.5 smooth-ish … 2 very ragged). |
| `rubble` | number | `1` | Amount of pebbles along the wall foot (0 = none). |
| `grid` | boolean | `true` | Draw the 5-ft grid (clipped to the floor). CLI `--no-grid` overrides. |

## chambers[]

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Unique name, referenced by passages. |
| `at` | `[x, y]` | Centre. Must be on floor (else QA FAIL). |
| `r` | `[rx, ry]` | Radii in cells. Nook 1.5–2, room 3–4, hall 6–10. |
| `rot` | number | Optional rotation in degrees. |
| `label` | string | Optional; drawn only in DM output. |

## passages[]

Either form, plus `width`:

| Field | Type | Meaning |
|---|---|---|
| `from`, `to` | string | Chamber id → chamber id, or chamber id → `north` / `south` / `east` / `west` (runs off that map edge). |
| `path` | array | Waypoints: chamber ids or `[x, y]` points; may end with an edge word. |
| `width` | number | Width in cells: 2 tight, 3 normal, 4–8 gallery. |

## pillars[] and pools[]

| Field | Type | Meaning |
|---|---|---|
| `at` | `[x, y]` | Centre (should be on floor). |
| `r` | `[rx, ry]` | Radii in cells. |
| `rot` | number | Optional rotation in degrees. |

## features[]

| Field | Type | Default | Meaning |
|---|---|---|---|
| `kind` | string | required | One of the asset kinds below. |
| `at` | `[x, y]` | required | Centre of the asset. |
| `rot` | number | `0` | Rotation in degrees. |
| `scale` | number | `1` | Size multiplier. |
| `label` | string | — | DM-only text label. |
| `secret` | boolean | `false` | If true, drawn only in DM output. |

`trap` features are always DM-only.

## Assets

Nominal footprint at `scale: 1` (cells, width × height before rotation). Each is drawn as black ink on a white fill.

| Kind | Footprint | Look |
|---|---|---|
| `boulder` | 1×1 | Large angular rock with a crack or two. |
| `rocks` | 1×1 | Cluster of 3 small stones. |
| `rubble` | 1×1 | Scatter of many small fragments. |
| `stalagmite` | 1×1 | Irregular rings around a dark tip. |
| `pillar` | 1×1 | Round worked column. |
| `mushrooms` | 1×1 | Group of round caps. |
| `bones` | 1×1 | Scattered long bones. |
| `skull` | ½×½ | Small skull. |
| `campfire` | 1×1 | Stone ring, crossed logs, flame. |
| `bedroll` | 1×2 | Rolled-out mat with pillow end. |
| `chest` | 1×1 | Banded box with lock. |
| `crate` | 1×1 | Square box with plank lines. |
| `barrel` | 1×1 | Round top with hoops. |
| `table` | 2×1 | Plank table. |
| `chair` | ½×½ | Small seat with back. |
| `torch` | ½×½ | Wall sconce / brazier with flame. |
| `stairs` | 1×2 | Steps with arrow pointing up (−y). |
| `door` | 1×½ | Wooden door in a frame. |
| `ladder` | 1×2 | Two rails with rungs. |
| `web` | 1×1 | Radial spider web. |
| `trap` | 1×1 | Dashed square with X (DM only). |
| `altar` | 2×1 | Stone block with top slab. |
| `statue` | 1×1 | Plinth with figure outline. |

## QA

| Level | Condition |
|---|---|
| FAIL | A chamber centre is in rock. |
| FAIL | A chamber is not connected to the first chamber. |
| WARN | An edge exit (`north`/`south`/`east`/`west`) does not reach the map edge. |
| WARN | A feature is in rock. |
| WARN | Floor share is outside 20–80 % of the map. |

Output: `QA <name>: n FAIL, n WARN`; the CLI exits 1 on any FAIL.
