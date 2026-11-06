# The ```cave fence

A `.yaml` file, or YAML inside a ```cave fence in a Markdown note. Coordinates and sizes are in
**cells** (1 cell = 5 ft), origin top-left, x right, y down. `r` is a radius: one number for a
circle or `[rx, ry]` for an ellipse. `rot` is degrees, clockwise.

| Key | Default | Meaning |
|---|---|---|
| `name` | Cave | title; its slug names the outputs (`<slug>.webp`, `<slug>-foundry.json`) |
| `size` | `[30, 30]` | map size in cells `[width, height]` |
| `seed` | 1 | every random choice (wall wobble, rubble, dots) |
| `px` | 100 | pixels per cell in the painted map (Foundry grid size) |
| `darkness` | 0.6 | opacity of the dark blue night layer |
| `roughness` | 1.0 | how jagged the walls are |
| `damp` | 1.0 | strength of the green wash along the walls |
| `rocks` | 14 | auto rubble: three in four hug a wall, every fourth lies loose |
| `puddles` | 4 | auto shallow puddles on open floor |

## Shapes

```yaml
chambers:            # open floor; smoothly merged where they meet
  - {id: mouth, at: [18, 24], r: [5, 3.5], rot: 0}
passages:            # tunnels; width in cells (2 = 10 ft)
  - {from: mouth, to: south, width: 4}            # north/south/east/west = run off that map edge
  - {path: [mouth, [14, 19.5], split], width: 3}  # waypoints: chamber ids or [x, y]
pillars:             # rock islands cut out of the floor (ledges, columns, tactical cover)
  - {at: [18, 19.6], r: [2.6, 1.6], rot: 0}
pools:               # deep water with a darker centre and ripple lines
  - {at: [29.5, 12], r: [2.8, 2], rot: 20, deep: true}
```

## Terrain inside the cave

```yaml
ledges:              # raised floor: a lighter top, an inked lip and a shadow on the floor below
  - {at: [20, 26.2], r: [2.6, 1.6], height: 5, label: Z2}
chasms:              # a pit: near-black, with lines stepping down into it (not a Foundry wall)
  - {at: [12, 20], r: [2, 1.2]}
streams:             # shallow water along a path
  - {path: [[31, 26], [28, 24.6], [23.6, 29.6]], width: 0.6}
stairs:              # rough-hewn steps; v runs along l, darker toward the bottom (down: false climbs)
  - {at: [11.2, 11.8], rot: 124, w: 2, l: 2.4, n: 6, down: true}
lava:                # glowing flows and pools: burns through the night layer and lights itself
  - {at: [44.6, 10.6], r: [2.6, 2], rot: 25}
  - {path: [[44, 12.5], [42, 20], [38.5, 26]], width: 2.4}
stalagmites: 10      # auto, on open floor near the walls
cracks: 4            # auto floor cracks; crack_paths: [[[x, y], ...]] draws given ones
```

Any chamber, ledge, passage or feature can carry `label:` (A1, D5 …): drawn on the `--preview` and the
`--dm` copy only. A passage with `secret: true` is not carved: the map shows rock, the DM overlay shows a
dashed red line. `features` kind `trap` is a red cross on the DM overlay and nothing on the map.

## Light and detail

```yaml
glow:                # glowing fungus / crystals: n dots within spread cells, each cluster a dim light
  - {at: [13.4, 13.6], n: 8, spread: 0.8, color: amber, light: 1}
features:
  - {kind: camp, at: [7, 6], rot: 0}   # bedroll + pack + fire 1.6 cells to the right, stain on the bedroll
  - {kind: fire, at: [8, 11], lit: true}
  - {kind: bones, at: [10, 13], r: 1.2, n: 6}
  - {kind: blood, at: [17, 25.5], r: 0.9}
  - {kind: carcass, at: [20.8, 36.6], rot: 95, r: 1.1}   # stripped beast: ribcage, legs, antlers
  - {kind: nest, at: [6.3, 22.6], r: 0.9}         # straw bed with a fur
  - {kind: cage, at: [5.2, 6.4], r: 1.3}          # plank lid weighed down by a rock
  - {kind: corpse, at: [3.5, 7.3], rot: 270, chained: true}   # chains run toward -v (rot 270 = west wall)
  - {kind: chains, at: [5, 5.8], to: [4.9, 5.2]}
  - {kind: statue, at: [4, 9], rot: 90, r: 1.2}   # a wolf-headed figure in a garland, on a plinth
  - {kind: treasure, at: [5.4, 9], r: 0.9}
  - {kind: moonbeam, at: [5, 9], r: 1.5}           # pale disc on the floor + a moon light
  - {kind: torch, at: [8.8, 5.9]}                 # wall sconce; lights itself
  - {kind: tracks, at: [20.5, 37.5], to: [19, 30.5]}
  - {kind: claws, at: [3.6, 24.5], rot: 90}       # also web, roots, moss, skull, spear, stalagmite,
                                                   # bedroll, pack, crate, altar
  - {kind: brazier, at: [12, 31.5]}               # lit iron fire bowl; lights itself
  - {kind: scorch, at: [39, 9.5], r: 3.2}         # soot wash (a dragon's bed, a fire-breath mark)
  - {kind: charred, at: [39, 9.5], r: 3.6, n: 18} # burnt bones
  - {kind: trap, at: [11, 45.5], label: T}        # DM overlay only
lights:              # extra lights; radius = dim radius in cells
  - {at: [20, 4], color: torch, radius: 4, bright: 1}
```

Glow colours: `amber`, `teal`, `pale-blue`, `violet`, `sickly-green`, `red`. Light colours: those plus
`fire`, `torch`, `candle`, `moon`.

## Output

- `<slug>.webp`: `size × px` pixels, no grid (Foundry draws its own).
- with `--dm`, `<slug>-dm.webp`: the same map with tags, secret ways and traps, for the DM.
- `<slug>-foundry.json`: `width`, `height`, `grid`, `walls` (`c: [x1, y1, x2, y2]` in
  scene pixels, traced along the wall line), `lights` (x, y in pixels; `dim`/`bright` in feet).
  A glow cluster exports half its painted radius as dim light, about 5 ft.
