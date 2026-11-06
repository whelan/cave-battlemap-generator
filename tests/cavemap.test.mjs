import test from 'node:test';
import assert from 'node:assert/strict';
import { renderCave, validate, ASSETS, assetSvg } from '../cavemap.js';

const SPEC = {
  name: 'Test Cave',
  size: [20, 16],
  seed: 7,
  chambers: [
    { id: 'mouth', at: [5, 10], r: [3.5, 3], rot: 0, label: 'A' },
    { id: 'back', at: [14, 6], r: [4, 3.2], label: 'B' },
  ],
  passages: [
    { from: 'mouth', to: 'south', width: 3 },
    { path: ['mouth', [9, 8], 'back'], width: 2.6 },
  ],
  pillars: [{ at: [15.8, 7.6], r: [1, 0.7] }],
  pools: [{ at: [16, 5], r: [1.4, 1] }],
  features: [
    { kind: 'campfire', at: [4, 9], rot: 0, scale: 1, label: '1' },
    { kind: 'trap', at: [5, 14] },
    { kind: 'chest', at: [12, 5], rot: 20 },
  ],
  roughness: 1,
  rubble: 1,
  grid: true,
};

const count = (s, re) => (s.match(re) || []).length;

function wellFormed(svg) {
  assert.match(svg, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg"/);
  assert.match(svg.trim(), /<\/svg>$/);
  assert.ok(!/NaN|undefined|Infinity/.test(svg), 'no NaN/undefined in output');
  // every opened element is closed
  const open = count(svg, /<(g|svg|defs|clipPath|text|title)[\s>]/g);
  const close = count(svg, /<\/(g|svg|defs|clipPath|text|title)>/g);
  assert.equal(open, close, 'balanced container tags');
}

test('renders a well-formed SVG of the right size', () => {
  const svg = renderCave(SPEC);
  wellFormed(svg);
  assert.match(svg, /viewBox="0 0 1400 1120"/);
  assert.match(svg, /id="wall"/);
  assert.match(svg, /id="floor"/);
  assert.ok(svg.length < 600_000, `SVG is ${svg.length} bytes`);
});

test('same seed gives identical output, other seed differs', () => {
  assert.equal(renderCave(SPEC), renderCave(structuredClone(SPEC)));
  assert.notEqual(renderCave(SPEC), renderCave({ ...SPEC, seed: 8 }));
});

test('grid has one line per cell boundary and can be turned off', () => {
  const svg = renderCave(SPEC);
  const grid = svg.match(/<g id="grid"[^>]*>(.*?)<\/g>/s)[1];
  assert.equal(count(grid, /<line /g), 20 + 1 + 16 + 1);
  assert.match(svg, /clip-path="url\(#cm-floor\)"/);
  assert.ok(!renderCave(SPEC, { grid: false }).includes('id="grid"'));
  assert.ok(!renderCave({ ...SPEC, grid: false }).includes('id="grid"'));
});

test('DM layer: labels and traps only with dm', () => {
  const player = renderCave(SPEC);
  const dm = renderCave(SPEC, { dm: true });
  assert.ok(!player.includes('id="dm"'));
  assert.ok(!player.includes('#cm-trap'));
  assert.ok(dm.includes('id="dm"'));
  assert.ok(dm.includes('#cm-trap'));
  assert.match(dm, />A<\/text>/);
  assert.match(dm, />1<\/text>/);
});

test('px scales the output', () => {
  const svg = renderCave(SPEC, { px: 35 });
  assert.match(svg, /viewBox="0 0 700 560"/);
});

test('validate: clean spec passes', () => {
  const qa = validate(SPEC);
  assert.deepEqual(qa.errors, []);
});

test('validate: FAIL on chamber in rock / disconnected, WARN on feature in rock', () => {
  const bad = structuredClone(SPEC);
  bad.chambers.push({ id: 'island', at: [17, 13], r: [1.5, 1.2] });
  bad.features.push({ kind: 'barrel', at: [19, 1] });
  const qa = validate(bad);
  assert.ok(qa.errors.some((e) => /island.*not connected/.test(e)), qa.errors.join('; '));
  assert.ok(qa.warnings.some((w) => /barrel.*rock/.test(w)), qa.warnings.join('; '));

  const rock = structuredClone(SPEC);
  rock.pillars.push({ at: [14, 6], r: [2.5, 2] });
  assert.ok(validate(rock).errors.some((e) => /rock/.test(e)));
});

test('validate: malformed specs report errors and renderCave throws', () => {
  assert.ok(validate({}).errors.length);
  const bad = { ...SPEC, passages: [{ from: 'mouth', to: 'nowhere' }] };
  assert.ok(validate(bad).errors.some((e) => /nowhere/.test(e)));
  assert.throws(() => renderCave(bad));
});

const NAMES = ['boulder', 'rocks', 'rubble', 'stalagmite', 'pillar', 'mushrooms', 'bones', 'skull', 'campfire', 'bedroll', 'chest',
  'crate', 'barrel', 'table', 'chair', 'torch', 'stairs', 'door', 'ladder', 'web', 'trap', 'altar', 'statue'];

test('every asset exists and renders standalone and on a map', () => {
  assert.deepEqual(Object.keys(ASSETS).sort(), [...NAMES].sort());
  for (const name of NAMES) {
    const a = ASSETS[name];
    assert.ok(a.w > 0 && a.h > 0 && a.svg.length > 20, name);
    const svg = assetSvg(name);
    wellFormed(svg);
    assert.match(svg, new RegExp(`viewBox="0 0 ${a.w * 100} ${a.h * 100}"`));
  }
  const spec = structuredClone(SPEC);
  spec.features = NAMES.map((kind, i) => ({ kind, at: [3 + (i % 5) * 0.8, 8 + Math.floor(i / 5) * 0.8], scale: 0.5 }));
  const svg = renderCave(spec, { dm: true });
  wellFormed(svg);
  for (const name of NAMES) assert.ok(svg.includes(`id="cm-${name}"`), name);
});
