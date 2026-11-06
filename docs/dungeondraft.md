# Dungeondraft export

`cave-dd SPEC` builds the same cave as a `.dungeondraft_map`: one level with

- **terrain**: a four-slot splat (4 samples per cell) of cave floor, rocky ground for the rock mass,
  calm water for pools and streams (lava uses the same slot), gravel on ledge tops;
- **walls**: `Rock-2-wall` along the same traced wall line as the Foundry json;
- **paths**: `Ridge_Cave` round every ledge;
- **objects**: every rubble stone, stalagmite, glow dot, puddle and feature at the painted map's
  position, scaled to its size in cells;
- **lights**: the painted map's lights.

## Packs

The asset index is built from Dungeondraft's custom assets folder: set `DDMAP_ASSETS`, or let it read
`custom_assets_directory` from Dungeondraft's `config.ini` (the macOS path is built in). The index is
cached in `~/.cache/cave-battlemap-generator/`. `python -m cavemap.ddassets find REGEX` lists
matching assets with pixel sizes; `python -m cavemap.ddassets catalog DIR` writes a compact,
greppable catalog of every pack, useful when tuning the mapping on a machine without the packs.

Without the packs, `--plan` still lists every object by kind and pattern, and the tests build a map
against a fake index.

## The mapping

`ASSETS` in `cavemap/dd.py` maps each kind to one or more regexes over asset paths. They are written
for the Forgotten Adventures packs plus AoA's scorch, char and fire effects:

| Kind | Asset | Note |
|---|---|---|
| rubble, stalagmite | `Rock_Stone_Slate_`, `Boulder_Stone_Slate_` | FA has no stalagmite; boulders stand in |
| glow | `Mushroom_<colour>` | |
| nest | `Hay_Pile` + `TC_Fur Blanket 01` | |
| cage | `Cage_Metal_Rusty_` | metal, where the painter draws wood |
| corpse, chains | `Skeleton_Humanoid_Yellowed`, `Chain_Metal_Rusty_Wall_Manacles` | skeletons for fresh corpses |
| statue | `Prefab_Grave_Statue_Prayer` | a stand-in; swap per cave |
| treasure | `Coins`, `Coin_Gold` | |
| torch, brazier, fire | `Sconce_…_Lit`, `Brazier_…_Lit`, `Campfire_Lit_01_A` | |
| lava | `CharGlowColorable` + `FirePatchA` | no lava texture in the packs |
| scorch, charred | `ScorchMarkColourable`, `CharMark`, burnt bones | |
| bones, skull, blood, carcass | FA bones, `Skull_Decor_Cracked`, `Blood_Puddle`, ribcage + `Deer_Skull` | |
| web, moss, tracks, spear, crate, bedroll, pack, altar, puddle, stairs | FA equivalents | |
| claws, roots, trap | none | painted map only; `--plan` names them |

`--check` lists every pattern that matches nothing in your packs.

## Not yet verified

The export has only been built against a fake asset index. On the first real run, open the map in
Dungeondraft and check that the walls face the right way, the terrain blend reads, and the
stand-ins look right from above.
