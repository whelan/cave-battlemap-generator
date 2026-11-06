#!/usr/bin/env node
// node cli.mjs spec.json [out.svg] [--dm] [--no-grid] [--px 70] [--color|--ink]
// node cli.mjs --assets assets/
import fs from 'node:fs';
import path from 'node:path';
import { renderCave, validate, ASSETS, assetSvg } from './cavemap.js';

const USAGE = `usage:
  node cli.mjs spec.json [out.svg] [--dm] [--no-grid] [--px 70] [--color|--ink]
  node cli.mjs --assets DIR`;

const args = process.argv.slice(2);
const flags = { dm: false, grid: undefined, px: 70, assets: null };
const pos = [];
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === '--dm') flags.dm = true;
  else if (a === '--no-grid') flags.grid = false;
  else if (a === '--px') flags.px = Number(args[++i]);
  else if (a === '--color') flags.style = 'color';
  else if (a === '--ink') flags.style = 'ink';
  else if (a === '--assets') flags.assets = args[++i] || 'assets';
  else if (a === '-h' || a === '--help') {
    console.log(USAGE);
    process.exit(0);
  } else if (a.startsWith('--')) {
    console.error(`unknown option ${a}\n${USAGE}`);
    process.exit(2);
  } else pos.push(a);
}

if (flags.assets) {
  fs.mkdirSync(flags.assets, { recursive: true });
  for (const name of Object.keys(ASSETS)) fs.writeFileSync(path.join(flags.assets, `${name}.svg`), assetSvg(name));
  console.log(`wrote ${Object.keys(ASSETS).length} assets to ${flags.assets}`);
  process.exit(0);
}

if (!pos.length) {
  console.error(USAGE);
  process.exit(2);
}
if (!(flags.px > 0)) {
  console.error('--px must be a positive number');
  process.exit(2);
}

const specPath = pos[0];
let spec;
try {
  spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
} catch (e) {
  console.error(`cannot read ${specPath}: ${e.message}`);
  process.exit(2);
}
const name = (spec && spec.name) || path.basename(specPath, path.extname(specPath));
const qa = validate(spec);
for (const e of qa.errors) console.log(`FAIL ${e}`);
for (const w of qa.warnings) console.log(`WARN ${w}`);

let ok = true;
try {
  const svg = renderCave(spec, { dm: flags.dm, grid: flags.grid, px: flags.px, style: flags.style });
  const out = pos[1] || specPath.replace(/\.json$/i, '') + (flags.dm ? '-dm' : '') + '.svg';
  fs.writeFileSync(out, svg);
  console.log(`wrote ${out} (${Math.round(svg.length / 1024)} KB)`);
} catch (e) {
  ok = false;
  console.error(e.message);
}
console.log(`QA ${name}: ${qa.errors.length} FAIL, ${qa.warnings.length} WARN`);
process.exit(qa.errors.length || !ok ? 1 : 0);
