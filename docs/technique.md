# How the painter works

Every shape in the spec becomes part of one signed distance field `d`, in cells: `d < 0` is open
floor, `d > 0` is rock, `d = 0` is the wall line. Chambers are ellipses, passages are capsules, both
merged with a smooth minimum so they flow into each other; pillars are cut back out. Noise lattices
are sized in cells, so the same seed gives the same cave at 24 px per cell and at 100.

The stages follow a hand-drawn cave tutorial; `--steps DIR` writes one image per stage.

| Step | What happens | Where to change it |
|---|---|---|
| 1. Outline | a soft, thick line along the smooth field, low-frequency wobble only | `roughness` |
| 2. Jagged line | finer noise added; a thin ink line where it crosses zero | `roughness` |
| 3. Depth | four more lines behind the wall and one in front, the outer ones broken into strokes; line width is divided by the field's slope so saddles don't smear | `wall_ink()` in `render.py` |
| 4. Details | rubble hugging the walls, loose stones, puddles, stalagmites, cracks, glow dots, every feature | `rocks`, `puddles`, `stalagmites`, `cracks`, `features`, `glow` |
| 5. Colour | earth tones with a watercolour texture, rock darkening into the mass, a damp green wash at the wall foot, water, blood, soot, ledge tops, pits, moonlight on the floor | `damp`, the palette constants in `render.py` |
| 6. Night | one dark blue layer multiplied over everything | `darkness` (0–1) |
| 7. Light and shade | each light's colour revealed through the night layer, stopped by walls (ray-marched visibility); blue shade built from the outside in, heaviest at the foot of the walls and nearest the lights; lava drawn last as its own light | light radii in `spec.all_lights()` |

## Lights

Lights come from the spec (`lights:`), from lit fires, camps, braziers and torches, from every glow
cluster, from moonbeams, and from lava (one light every three cells along a flow). The Foundry json
exports the same list, with radii in feet: fire flickers (`torch` animation), fungus pulses.

## Walls for Foundry

The wall line is traced with marching squares on the jagged field at four samples per cell,
chained into polylines and simplified to within an eighth of a cell, so the walls follow the ink.
The map edge stays open (tunnels that run off the map are exits), secret passages stay rock (make
the door yourself when it is found), and pits, lava and ledges are not walls.

## Placement

Rubble, puddles, stalagmites, cracks and the dots of each glow cluster are placed on a fixed
8-samples-per-cell field from a seeded RNG, so they land in the same place at every render size.
They avoid features, pools and each other.
