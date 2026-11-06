// cavemap.js — dependency-free cave battlemap generator (ink line drawing, 5-ft grid).
// ES module for browsers and Node >= 18.
//
//   renderCave(spec, {px, dm, grid}) -> SVG string
//   validate(spec) -> {errors, warnings}
//   ASSETS[name] = {w, h, svg}   (svg: inner markup, 100 units per cell)
//   assetSvg(name) -> standalone SVG string
//
// Everything is measured in cells (1 cell = 5 ft) and drawn from one signed distance field:
// d < 0 is floor, d > 0 is rock, d = 0 is the wall. Noise lattices are sized in cells, so the
// same seed gives the same cave at any pixel size.

const RES = 4; // field samples per cell (marching squares)
const PAD = 2; // cells of field outside the map on each side
const EDGES = ['north', 'south', 'east', 'west'];
const INK = '#000';

// ---------------------------------------------------------------- random + noise

function hashKey(...parts) {
  let h = 0x811c9dc5;
  const s = parts.map(String).join('|');
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  h ^= h >>> 15;
  h = Math.imul(h, 0x2c1b3c6d);
  h ^= h >>> 12;
  return h >>> 0;
}

function rng(...key) {
  let a = hashKey(...key);
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function cr(a, b, c, d, t) {
  return b + 0.5 * t * (c - a + t * (2 * a - 5 * b + 4 * c - d + t * (3 * (b - c) + d - a)));
}

// Smooth value noise, roughly in [-1, 1]; `scale` is the lattice spacing in cells.
function makeNoise(W, H, scale, ...key) {
  const off = PAD + 3;
  const gw = Math.ceil((W + 2 * off) / scale) + 4;
  const gh = Math.ceil((H + 2 * off) / scale) + 4;
  const r = rng(...key);
  const lat = new Float64Array(gw * gh);
  for (let i = 0; i < lat.length; i++) lat[i] = r() * 2 - 1;
  const at = (i, j) => lat[Math.min(gh - 1, Math.max(0, j)) * gw + Math.min(gw - 1, Math.max(0, i))];
  return (x, y) => {
    const u = (x + off) / scale + 1, v = (y + off) / scale + 1;
    const i = Math.floor(u), j = Math.floor(v), fx = u - i, fy = v - j;
    const row = (jj) => cr(at(i - 1, jj), at(i, jj), at(i + 1, jj), at(i + 2, jj), fx);
    return cr(row(j - 1), row(j), row(j + 1), row(j + 2), fy);
  };
}

function makeFbm(W, H, scale, octaves, ...key) {
  const ns = [];
  let amp = 1, tot = 0;
  for (let o = 0; o < octaves; o++) {
    ns.push([amp, makeNoise(W, H, scale / 2 ** o, ...key, o)]);
    tot += amp;
    amp *= 0.5;
  }
  return (x, y) => {
    let s = 0;
    for (const [a, n] of ns) s += a * n(x, y);
    return s / tot;
  };
}

// ---------------------------------------------------------------- distance primitives

function sdEllipse(x, y, at, r, rot) {
  const c = Math.cos(rot), s = Math.sin(rot);
  const dx = x - at[0], dy = y - at[1];
  const u = c * dx + s * dy, v = -s * dx + c * dy;
  return (Math.hypot(u / r[0], v / r[1]) - 1) * Math.min(r[0], r[1]);
}

function sdCapsule(x, y, a, b, rad) {
  const bx = b[0] - a[0], by = b[1] - a[1], px = x - a[0], py = y - a[1];
  const h = Math.min(1, Math.max(0, (px * bx + py * by) / Math.max(bx * bx + by * by, 1e-9)));
  return Math.hypot(px - bx * h, py - by * h) - rad;
}

function smin(a, b, k) {
  const h = Math.max(k - Math.abs(a - b), 0) / k;
  return Math.min(a, b) - h * h * k * 0.25;
}

const smooth = (e0, e1, x) => {
  const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0)));
  return t * t * (3 - 2 * t);
};

// ---------------------------------------------------------------- spec

const isPt = (p) => Array.isArray(p) && p.length === 2 && p.every((v) => typeof v === 'number' && isFinite(v));

function radii(r, def) {
  if (r === undefined) return [def, def];
  if (typeof r === 'number') return [r, r];
  if (Array.isArray(r) && r.length === 2 && r.every((v) => typeof v === 'number' && v > 0)) return r;
  return null;
}

function normalize(spec) {
  const errors = [], warnings = [];
  const s = { chambers: [], passages: [], pillars: [], pools: [], features: [], exits: [] };
  if (!spec || typeof spec !== 'object') return { s, errors: ['spec must be a JSON object'], warnings };
  s.name = typeof spec.name === 'string' && spec.name ? spec.name : 'Cave';
  const size = spec.size;
  if (!isPt(size) || size[0] < 4 || size[1] < 4 || size[0] > 400 || size[1] > 400) {
    errors.push('size must be [w, h] in cells (4..400)');
    return { s, errors, warnings };
  }
  s.W = Math.round(size[0]);
  s.H = Math.round(size[1]);
  s.seed = spec.seed ?? 1;
  s.roughness = typeof spec.roughness === 'number' ? Math.max(0, spec.roughness) : 1;
  s.rubble = typeof spec.rubble === 'number' ? Math.max(0, spec.rubble) : 1;
  s.grid = spec.grid !== false;

  const ids = new Map();
  (spec.chambers || []).forEach((c, i) => {
    const w = `chambers[${i}]`;
    if (!c || !isPt(c.at)) return errors.push(`${w}: "at" must be [x, y]`);
    const r = radii(c.r, 3);
    if (!r) return errors.push(`${w}: "r" must be a number or [rx, ry] > 0`);
    const ch = { id: c.id ?? `#${i}`, at: c.at, r, rot: ((c.rot || 0) * Math.PI) / 180, label: c.label, where: w };
    if (ids.has(ch.id)) errors.push(`${w}: duplicate id "${ch.id}"`);
    ids.set(ch.id, ch);
    s.chambers.push(ch);
  });
  if (!s.chambers.length) errors.push('at least one chamber is required');

  (spec.passages || []).forEach((p, i) => {
    const w = `passages[${i}]`;
    const raw = p && (Array.isArray(p.path) ? p.path : [p.from, p.to]);
    if (!raw || raw.length < 2) return errors.push(`${w}: needs "from"/"to" or a "path" of 2+ points`);
    const pts = [];
    let bad = false;
    raw.forEach((q, j) => {
      if (isPt(q)) pts.push(q);
      else if (typeof q === 'string' && ids.has(q)) pts.push(ids.get(q).at);
      else if (typeof q === 'string' && EDGES.includes(q)) pts.push(q);
      else {
        errors.push(`${w}: unknown chamber, edge or point ${JSON.stringify(q)}`);
        bad = true;
      }
    });
    if (bad) return;
    const out = [];
    for (let j = 0; j < pts.length; j++) {
      let q = pts[j];
      if (typeof q === 'string') {
        const nb = j ? pts[j - 1] : pts[1];
        if (typeof nb === 'string') {
          errors.push(`${w}: two edges in a row`);
          return;
        }
        const [x, y] = nb;
        const e = { north: [x, -PAD], south: [x, s.H + PAD], west: [-PAD, y], east: [s.W + PAD, y] }[q];
        s.exits.push({ where: w, edge: q, from: nb, to: e });
        q = e;
      }
      out.push(q);
    }
    const width = typeof p.width === 'number' && p.width > 0 ? p.width : 2.5;
    s.passages.push({ pts: out, width, where: w });
  });

  for (const key of ['pillars', 'pools']) {
    (spec[key] || []).forEach((q, i) => {
      const w = `${key}[${i}]`;
      if (!q || !isPt(q.at)) return errors.push(`${w}: "at" must be [x, y]`);
      const r = radii(q.r, key === 'pillars' ? 1 : 1.5);
      if (!r) return errors.push(`${w}: "r" must be a number or [rx, ry] > 0`);
      s[key].push({ at: q.at, r, rot: ((q.rot || 0) * Math.PI) / 180, where: w });
    });
  }

  (spec.features || []).forEach((f, i) => {
    const w = `features[${i}]`;
    if (!f || typeof f.kind !== 'string') return errors.push(`${w}: "kind" is required`);
    if (!isPt(f.at)) return errors.push(`${w}: "at" must be [x, y]`);
    if (!ASSETS[f.kind] && f.kind !== 'secret') warnings.push(`${w}: unknown kind "${f.kind}" (drawn as a marker)`);
    const scale = typeof f.scale === 'number' && f.scale > 0 ? f.scale : 1;
    const a = ASSETS[f.kind] || { w: 1, h: 1 };
    s.features.push({
      kind: f.kind, at: f.at, rot: f.rot || 0, scale, label: f.label, where: w,
      dmOnly: f.kind === 'trap' || f.kind === 'secret' || f.secret === true,
      rad: 0.5 * scale * Math.hypot(a.w, a.h) * 0.8,
    });
  });
  return { s, errors, warnings };
}

// ---------------------------------------------------------------- field

function buildField(s) {
  const { W, H } = s;
  const k = s.seed;
  const n1 = makeFbm(W, H, 5.0, 2, k, 1);
  const n2 = makeFbm(W, H, 1.2, 2, k, 2);
  const n3 = makeNoise(W, H, 0.45, k, 3);
  const r = s.roughness;
  const base = (x, y) => {
    let d = null;
    for (const c of s.chambers) {
      const e = sdEllipse(x, y, c.at, c.r, c.rot);
      d = d === null ? e : smin(d, e, 2.0);
    }
    for (const p of s.passages)
      for (let i = 0; i + 1 < p.pts.length; i++) d = smin(d, sdCapsule(x, y, p.pts[i], p.pts[i + 1], p.width / 2), 1.6);
    for (const q of s.pillars) d = -smin(-d, sdEllipse(x, y, q.at, q.r, q.rot), 1.0);
    return d;
  };
  const nx = (W + 2 * PAD) * RES + 1, ny = (H + 2 * PAD) * RES + 1;
  const g = new Float64Array(nx * ny);
  for (let j = 0; j < ny; j++)
    for (let i = 0; i < nx; i++) {
      const x = -PAD + i / RES, y = -PAD + j / RES;
      let d = base(x, y) + r * (0.32 * n1(x, y) + 0.2 * n2(x, y) + 0.09 * n3(x, y));
      if (i === 0 || j === 0 || i === nx - 1 || j === ny - 1) d = Math.max(d, 0.3);
      g[j * nx + i] = d;
    }
  const F = { g, nx, ny, x0: -PAD, y0: -PAD, step: 1 / RES };
  F.at = (x, y) => sampleGrid(F, x, y);
  F.grad = (x, y) => {
    const h = 0.2;
    const gx = F.at(x + h, y) - F.at(x - h, y), gy = F.at(x, y + h) - F.at(x, y - h);
    const l = Math.hypot(gx, gy) || 1;
    return [gx / l, gy / l];
  };
  return F;
}

function sampleGrid(F, x, y) {
  const u = (x - F.x0) / F.step, v = (y - F.y0) / F.step;
  if (u < 0 || v < 0 || u > F.nx - 1 || v > F.ny - 1) return 1;
  const i = Math.min(F.nx - 2, Math.floor(u)), j = Math.min(F.ny - 2, Math.floor(v));
  const fx = u - i, fy = v - j, g = F.g, n = F.nx;
  const a = g[j * n + i], b = g[j * n + i + 1], c = g[(j + 1) * n + i], d = g[(j + 1) * n + i + 1];
  return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy;
}

// ---------------------------------------------------------------- contours

// Marching squares on a grid {g,nx,ny,x0,y0,step}; returns [{pts, closed}] for value == iso.
function contours(F, iso, g = F.g) {
  const { nx, ny, x0, y0, step } = F;
  const pos = new Map();
  const adj = new Map();
  const ein = (v) => v < iso;
  const pt = (id) => {
    if (pos.has(id)) return;
    const h = id & 1, c = id >> 1, i = c % nx, j = (c - i) / nx;
    const a = g[c], b = h ? g[c + nx] : g[c + 1];
    const t = Math.abs(b - a) < 1e-12 ? 0.5 : (iso - a) / (b - a);
    pos.set(id, h ? [x0 + i * step, y0 + (j + t) * step] : [x0 + (i + t) * step, y0 + j * step]);
  };
  const link = (p, q) => {
    pt(p);
    pt(q);
    if (!adj.has(p)) adj.set(p, []);
    if (!adj.has(q)) adj.set(q, []);
    adj.get(p).push(q);
    adj.get(q).push(p);
  };
  for (let j = 0; j < ny - 1; j++)
    for (let i = 0; i < nx - 1; i++) {
      const c = j * nx + i;
      const v00 = g[c], v10 = g[c + 1], v01 = g[c + nx], v11 = g[c + nx + 1];
      const b00 = ein(v00), b10 = ein(v10), b01 = ein(v01), b11 = ein(v11);
      const T = 2 * c, B = 2 * (c + nx), L = 2 * c + 1, R = 2 * (c + 1) + 1;
      const es = [];
      if (b00 !== b10) es.push(T);
      if (b10 !== b11) es.push(R);
      if (b11 !== b01) es.push(B);
      if (b01 !== b00) es.push(L);
      if (es.length === 2) link(es[0], es[1]);
      else if (es.length === 4) {
        const centre = ein((v00 + v10 + v01 + v11) / 4);
        if (centre === b10) {
          link(L, T);
          link(R, B);
        } else {
          link(T, R);
          link(B, L);
        }
      }
    }
  const seen = new Set();
  const out = [];
  const walk = (start) => {
    const ids = [start];
    seen.add(start);
    let cur = start;
    for (;;) {
      const nxt = adj.get(cur).find((q) => !seen.has(q));
      if (nxt === undefined) break;
      seen.add(nxt);
      ids.push(nxt);
      cur = nxt;
    }
    const closed = ids.length > 2 && adj.get(cur).includes(start);
    return { pts: ids.map((id) => pos.get(id)), closed };
  };
  for (const [id, a] of adj) if (a.length === 1 && !seen.has(id)) out.push(walk(id));
  for (const id of adj.keys()) if (!seen.has(id)) out.push(walk(id));
  return out;
}

function rdp(pts, tol) {
  if (pts.length < 3) return pts.slice();
  const keep = new Uint8Array(pts.length);
  keep[0] = keep[pts.length - 1] = 1;
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [a, b] = stack.pop();
    const [ax, ay] = pts[a], [bx, by] = pts[b];
    const dx = bx - ax, dy = by - ay, l = Math.hypot(dx, dy) || 1e-9;
    let best = -1, bi = -1;
    for (let i = a + 1; i < b; i++) {
      const dd = Math.abs((pts[i][0] - ax) * dy - (pts[i][1] - ay) * dx) / l;
      if (dd > best) (best = dd), (bi = i);
    }
    if (best > tol) {
      keep[bi] = 1;
      stack.push([a, bi], [bi, b]);
    }
  }
  return pts.filter((_, i) => keep[i]);
}

function simplify(c, tol) {
  if (!c.closed) return { pts: rdp(c.pts, tol), closed: false };
  const p = c.pts;
  let far = 0, fd = -1;
  for (let i = 1; i < p.length; i++) {
    const dd = Math.hypot(p[i][0] - p[0][0], p[i][1] - p[0][1]);
    if (dd > fd) (fd = dd), (far = i);
  }
  const a = rdp(p.slice(0, far + 1), tol), b = rdp([...p.slice(far), p[0]], tol);
  return { pts: [...a, ...b.slice(1, -1)], closed: true };
}

function chaikin(c, t = 0.25) {
  const p = c.pts, n = p.length, out = [];
  if (n < 3) return c;
  const lim = c.closed ? n : n - 1;
  if (!c.closed) out.push(p[0]);
  for (let i = 0; i < lim; i++) {
    const a = p[i], b = p[(i + 1) % n];
    out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
    out.push([a[0] + (b[0] - a[0]) * (1 - t), a[1] + (b[1] - a[1]) * (1 - t)]);
  }
  if (!c.closed) out.push(p[n - 1]);
  return { pts: out, closed: c.closed };
}

const loopArea = (p) => {
  let a = 0;
  for (let i = 0; i < p.length; i++) {
    const q = p[(i + 1) % p.length];
    a += p[i][0] * q[1] - q[0] * p[i][1];
  }
  return a / 2;
};

// ---------------------------------------------------------------- svg helpers

const f1 = (v) => {
  const r = Math.round(v * 10) / 10;
  return Object.is(r, -0) ? '0' : String(r);
};
const f2 = (v) => {
  const r = Math.round(v * 100) / 100;
  return Object.is(r, -0) ? '0' : String(r);
};

function polyD(pts, closed, S) {
  let d = `M${f1(pts[0][0] * S)} ${f1(pts[0][1] * S)}`;
  for (let i = 1; i < pts.length; i++) d += `L${f1(pts[i][0] * S)} ${f1(pts[i][1] * S)}`;
  return closed ? d + 'Z' : d;
}

// Rounded closed blob through the midpoints of pts (quadratic curves).
function blobD(pts, S = 1, fmt = f1) {
  const n = pts.length;
  const m = (i) => {
    const a = pts[i % n], b = pts[(i + 1) % n];
    return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  };
  let s0 = m(0);
  let d = `M${fmt(s0[0] * S)} ${fmt(s0[1] * S)}`;
  for (let i = 1; i <= n; i++) {
    const c = pts[i % n], e = m(i);
    d += `Q${fmt(c[0] * S)} ${fmt(c[1] * S)} ${fmt(e[0] * S)} ${fmt(e[1] * S)}`;
  }
  return d + 'Z';
}

function stonePts(cx, cy, r, n, rand, jit = 0.3) {
  const a0 = rand() * Math.PI * 2;
  const pts = [];
  for (let i = 0; i < n; i++) {
    const a = a0 + ((i + (rand() - 0.5) * 0.5) / n) * Math.PI * 2;
    const rr = r * (1 - jit / 2 + jit * rand());
    pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr * (0.75 + 0.25 * rand())]);
  }
  return pts;
}

const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

// Spatial hash for "is anything within r of this point".
function spatial(cell = 0.5) {
  const m = new Map();
  const key = (i, j) => i * 73856093 + j * 19349663;
  return {
    add(x, y, r) {
      const k = key(Math.floor(x / cell), Math.floor(y / cell));
      if (!m.has(k)) m.set(k, []);
      m.get(k).push([x, y, r]);
    },
    hit(x, y, r, maxR = cell) {
      const reach = Math.ceil((r + maxR) / cell);
      const ci = Math.floor(x / cell), cj = Math.floor(y / cell);
      for (let i = ci - reach; i <= ci + reach; i++)
        for (let j = cj - reach; j <= cj + reach; j++) {
          const b = m.get(key(i, j));
          if (b) for (const [px, py, pr] of b) if (Math.hypot(px - x, py - y) < r + pr) return true;
        }
      return false;
    },
  };
}

// ---------------------------------------------------------------- model

function buildModel(spec) {
  const { s, errors, warnings } = normalize(spec);
  if (errors.length) return { s, errors, warnings };
  const F = buildField(s);
  return { s, F, errors, warnings };
}

// Pools: own field on a fine grid; returns {F, at} or null.
function poolField(s) {
  if (!s.pools.length) return null;
  const n = makeFbm(s.W, s.H, 1.0, 2, s.seed, 7);
  const res = 8;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const p of s.pools) {
    const m = Math.max(p.r[0], p.r[1]) + 1;
    x0 = Math.min(x0, p.at[0] - m);
    y0 = Math.min(y0, p.at[1] - m);
    x1 = Math.max(x1, p.at[0] + m);
    y1 = Math.max(y1, p.at[1] + m);
  }
  x0 = Math.floor(x0);
  y0 = Math.floor(y0);
  const nx = Math.ceil((x1 - x0) * res) + 1, ny = Math.ceil((y1 - y0) * res) + 1;
  const g = new Float64Array(nx * ny);
  for (let j = 0; j < ny; j++)
    for (let i = 0; i < nx; i++) {
      const x = x0 + i / res, y = y0 + j / res;
      let d = Infinity;
      for (const p of s.pools) d = Math.min(d, sdEllipse(x, y, p.at, p.r, p.rot));
      d += 0.25 * n(x, y);
      if (i === 0 || j === 0 || i === nx - 1 || j === ny - 1) d = Math.max(d, 0.5);
      g[j * nx + i] = d;
    }
  const P = { g, nx, ny, x0, y0, step: 1 / res };
  P.at = (x, y) => sampleGrid(P, x, y);
  return P;
}

// ---------------------------------------------------------------- validate

export function validate(spec) {
  const m = buildModel(spec);
  const errors = [...m.errors], warnings = [...m.warnings];
  if (errors.length) return { errors, warnings };
  const { s, F } = m;
  const { W, H } = s;
  // inner samples, flood fill from the first chamber
  const i0 = PAD * RES, i1 = (W + PAD) * RES, j0 = PAD * RES, j1 = (H + PAD) * RES;
  const nearestFloor = (at) => {
    let best = null, bd = Infinity;
    const ci = Math.round((at[0] - F.x0) * RES), cj = Math.round((at[1] - F.y0) * RES);
    for (let j = cj - RES; j <= cj + RES; j++)
      for (let i = ci - RES; i <= ci + RES; i++) {
        if (i < i0 || i > i1 || j < j0 || j > j1) continue;
        if (F.g[j * F.nx + i] >= 0) continue;
        const dd = Math.hypot(i - ci, j - cj);
        if (dd < bd) (bd = dd), (best = j * F.nx + i);
      }
    return best;
  };
  let floor = 0, total = 0;
  for (let j = j0; j <= j1; j++)
    for (let i = i0; i <= i1; i++) {
      total++;
      if (F.g[j * F.nx + i] < 0) floor++;
    }
  const reach = new Uint8Array(F.g.length);
  const start = nearestFloor(s.chambers[0].at);
  if (start !== null) {
    const st = [start];
    reach[start] = 1;
    while (st.length) {
      const c = st.pop();
      const i = c % F.nx, j = (c - i) / F.nx;
      for (const [di, dj] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const ii = i + di, jj = j + dj;
        if (ii < i0 || ii > i1 || jj < j0 || jj > j1) continue;
        const q = jj * F.nx + ii;
        if (!reach[q] && F.g[q] < 0) (reach[q] = 1), st.push(q);
      }
    }
  }
  s.chambers.forEach((c, n) => {
    if (F.at(c.at[0], c.at[1]) >= 0) errors.push(`${c.where} "${c.id}": centre is in rock`);
    else if (n > 0) {
      const q = nearestFloor(c.at);
      if (q === null || !reach[q]) errors.push(`${c.where} "${c.id}": not connected to "${s.chambers[0].id}"`);
    }
  });
  for (const e of s.exits) {
    const t = 0.15;
    const [x, y] = e.from;
    const p = { north: [x, t], south: [x, H - t], west: [t, y], east: [W - t, y] }[e.edge];
    const c = [Math.min(W - t, Math.max(t, p[0])), Math.min(H - t, Math.max(t, p[1]))];
    if (F.at(c[0], c[1]) >= 0) warnings.push(`${e.where}: exit "${e.edge}" does not reach the map edge`);
  }
  for (const f of s.features) {
    const d = F.at(f.at[0], f.at[1]);
    const lim = ['door', 'torch', 'secret', 'web', 'ladder'].includes(f.kind) ? 0.8 : 0.1;
    if (d > lim) warnings.push(`${f.where} (${f.kind}): sits in rock`);
    if (f.at[0] < 0 || f.at[1] < 0 || f.at[0] > W || f.at[1] > H) warnings.push(`${f.where} (${f.kind}): outside the map`);
  }
  const share = floor / total;
  if (share < 0.2 || share > 0.8) warnings.push(`floor covers ${Math.round(share * 100)}% of the map (want 20-80%)`);
  return { errors, warnings };
}

// ---------------------------------------------------------------- render

export function renderCave(spec, opts = {}) {
  const m = buildModel(spec);
  if (m.errors.length) throw new Error('invalid cave spec:\n  ' + m.errors.join('\n  '));
  const { s, F } = m;
  const px = opts.px > 0 ? opts.px : 70;
  const dm = !!opts.dm;
  const showGrid = opts.grid ?? s.grid;
  const { W, H, seed } = s;
  const S = px; // cells -> px
  const lw = (cellsAt70) => f2(cellsAt70 * (px / 70)); // stroke width given in px @70

  // --- wall loops
  const raw = contours(F, 0);
  const loops = raw
    .map((c) => chaikin(simplify(c, 0.04), 0.14))
    .filter((c) => c.pts.length > 3 && (!c.closed || Math.abs(loopArea(c.pts)) > 0.02));
  const floorD = loops.map((c) => polyD(c.pts, c.closed, S)).join('');

  // --- wall: filled variable-width band along each loop
  const wn = makeNoise(W, H, 1.3, seed, 20);
  const wn2 = makeNoise(W, H, 0.4, seed, 21);
  let wallD = '';
  for (const c of loops) {
    const p = c.pts, n = p.length;
    const L = [], R = [];
    for (let i = 0; i < n; i++) {
      const a = p[c.closed ? (i - 1 + n) % n : Math.max(0, i - 1)];
      const b = p[c.closed ? (i + 1) % n : Math.min(n - 1, i + 1)];
      let tx = b[0] - a[0], ty = b[1] - a[1];
      const tl = Math.hypot(tx, ty) || 1;
      tx /= tl;
      ty /= tl;
      const w = (3.1 / 70) * (1 + 0.32 * wn(p[i][0], p[i][1]) + 0.12 * wn2(p[i][0], p[i][1])) / 2;
      L.push([p[i][0] - ty * w, p[i][1] + tx * w]);
      R.push([p[i][0] + ty * w, p[i][1] - tx * w]);
    }
    if (c.closed) wallD += polyD(L, true, S) + polyD(R.reverse(), true, S);
    else wallD += polyD([...L, ...R.reverse()], true, S);
  }

  // --- depth lines behind the wall: broken offset contours
  let depthD = '';
  const depth = [
    [0.2, 0.55, 1.25],
    [0.48, 0.45, 0.95],
  ];
  depth.forEach(([off, keep], li) => {
    const wob = makeNoise(W, H, 0.7, seed, 50 + li);
    const gate = makeNoise(W, H, 0.55, seed, 60 + li);
    const g2 = new Float64Array(F.g.length);
    for (let j = 0; j < F.ny; j++)
      for (let i = 0; i < F.nx; i++) {
        const k = j * F.nx + i;
        g2[k] = F.g[k] + 0.06 * wob(F.x0 + i * F.step, F.y0 + j * F.step);
      }
    for (const c0 of contours(F, off, g2)) {
      const c = chaikin(simplify(c0, 0.04));
      let run = [];
      const flush = () => {
        if (run.length > 2) depthD += polyD(run, false, S);
        run = [];
      };
      for (const q of c.pts) {
        if (q[0] < -0.5 || q[1] < -0.5 || q[0] > W + 0.5 || q[1] > H + 0.5) {
          flush();
          continue;
        }
        if (gate(q[0], q[1]) > 0.5 - keep) run.push(q);
        else flush();
      }
      flush();
    }
  });

  // --- hatching: clusters of short parallel strokes in the rock band
  const R1 = rng(seed, 'hatch');
  const reachN = makeNoise(W, H, 1.6, seed, 30);
  const band = (x, y) => 1.15 + 0.45 * reachN(x, y);
  const cand = [];
  const hs = 1 / 6;
  for (let y = -0.5; y < H + 0.5; y += hs)
    for (let x = -0.5; x < W + 0.5; x += hs) {
      const cx = x + R1() * hs, cy = y + R1() * hs;
      const d = F.at(cx, cy);
      if (d > 0.08 && d < band(cx, cy)) cand.push([cx, cy, d, R1()]);
    }
  cand.sort((a, b) => a[3] - b[3]);
  const hh = spatial(0.5);
  let hatchD = '';
  for (const [cx, cy, d] of cand) {
    const t = d / band(cx, cy);
    const rmin = 0.24 + 0.12 * t;
    if (hh.hit(cx, cy, rmin, 0)) continue;
    if (R1() < t * t * 0.6) continue; // sparser as it fades out
    hh.add(cx, cy, 0);
    const [gx, gy] = F.grad(cx, cy);
    const ang = Math.atan2(gy, gx) + (R1() - 0.5) * 1.3;
    const ux = Math.cos(ang), uy = Math.sin(ang), vx = -uy, vy = ux;
    const ns = 3 + Math.floor(R1() * 2.2);
    const sp = 0.085;
    const len = (0.3 + 0.18 * R1()) * (1 - 0.45 * t);
    for (let k = 0; k < ns; k++) {
      const o = (k - (ns - 1) / 2) * sp + (R1() - 0.5) * 0.02;
      const l = len * (0.75 + 0.35 * R1()) * (k === 0 || k === ns - 1 ? 0.8 : 1);
      const sh = (R1() - 0.5) * 0.08;
      let a = [cx + vx * o + ux * (sh - l / 2), cy + vy * o + uy * (sh - l / 2)];
      let b = [cx + vx * o + ux * (sh + l / 2), cy + vy * o + uy * (sh + l / 2)];
      const ok = (p) => F.at(p[0], p[1]) > 0.03;
      if (!ok(a) && !ok(b)) continue;
      for (let it = 0; it < 4 && !ok(a); it++) a = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      for (let it = 0; it < 4 && !ok(b); it++) b = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      if (!ok(a) || !ok(b) || Math.hypot(b[0] - a[0], b[1] - a[1]) < 0.08) continue;
      hatchD += `M${f1(a[0] * S)} ${f1(a[1] * S)}l${f1((b[0] - a[0]) * S)} ${f1((b[1] - a[1]) * S)}`;
    }
  }

  // --- pools
  const P = poolField(s);
  let poolOut = '', poolFill = '';
  if (P) {
    const gate = makeNoise(W, H, 0.5, seed, 90);
    const lines = [
      [0, 1.5, 2],
      [-0.2, 0.9, 0.35],
      [-0.42, 0.75, 0.05],
      [-0.65, 0.6, -0.15],
    ];
    for (const [iso, width, keep] of lines) {
      let dd = '';
      for (const c0 of contours(P, iso)) {
        const c = chaikin(chaikin(simplify(c0, 0.02)));
        if (c.pts.length < 4) continue;
        if (iso === 0) {
          poolFill += polyD(c.pts, true, S);
          dd += polyD(c.pts, true, S);
          continue;
        }
        let run = [];
        const flush = () => {
          if (run.length > 2) dd += polyD(run, false, S);
          run = [];
        };
        for (const q of [...c.pts, c.pts[0]]) {
          if (gate(q[0] + iso * 3, q[1]) > -keep) run.push(q);
          else flush();
        }
        flush();
      }
      if (dd) poolOut += `<path d="${dd}" stroke-width="${lw(width)}"/>`;
    }
  }
  const inPool = (x, y, m = 0) => (P ? P.at(x, y) < m : false);

  // --- floor details: rubble at the wall foot, loose stones, cracks
  const occ = spatial(0.5);
  const featR = s.features.filter((f) => !f.dmOnly || dm);
  const nearFeature = (x, y, r) => featR.some((f) => Math.hypot(f.at[0] - x, f.at[1] - y) < f.rad + r);
  const free = (x, y, r) => !nearFeature(x, y, r) && !inPool(x, y, 0.15 + r) && !occ.hit(x, y, r + 0.02, 0.2);
  const R2 = rng(seed, 'rubble');
  const patch = makeFbm(W, H, 1.6, 2, seed, 40);
  let stoneD = '', crackD = '', dotD = '';
  const rub = s.rubble;
  if (rub > 0) {
    const st = 0.1;
    const cands = [];
    for (let y = 0; y < H; y += st)
      for (let x = 0; x < W; x += st) cands.push([x + R2() * st, y + R2() * st, R2()]);
    cands.sort((a, b) => a[2] - b[2]);
    for (const [x, y] of cands) {
      const d = F.at(x, y);
      if (d >= -0.02) continue;
      const foot = -d < 0.5 * Math.min(1.5, rub) + 0.1;
      if (foot) {
        const pr = Math.min(1, rub) * (0.35 + 0.65 * smooth(-0.35, 0.45, patch(x, y))) * Math.exp(d / 0.22);
        if (R2() > pr * 0.9) continue;
        const big = R2() < 0.06;
        const r = big ? 0.12 + R2() * 0.08 : (0.035 + R2() * 0.075) * (0.7 + 0.5 * Math.exp(d / 0.2));
        if (d + r * 0.6 > 0 || !free(x, y, r)) continue;
        occ.add(x, y, r);
        const pts = stonePts(x, y, r, 5 + Math.floor(R2() * 3), R2, 0.35);
        stoneD += blobD(pts, S);
        if (r > 0.08 && R2() < 0.4) {
          const a = R2() * Math.PI;
          stoneD += `M${f1((x - Math.cos(a) * r * 0.4) * S)} ${f1((y - Math.sin(a) * r * 0.4) * S)}l${f1(Math.cos(a) * r * 0.6 * S)} ${f1(Math.sin(a) * r * 0.6 * S)}`;
        }
      } else if (R2() < 0.012 * rub) {
        if (R2() < 0.45) {
          // a little gravel: three dots
          if (!free(x, y, 0.1)) continue;
          occ.add(x, y, 0.08);
          for (let k = 0; k < 3; k++) {
            const dx = (R2() - 0.5) * 0.18, dy = (R2() - 0.5) * 0.18;
            dotD += `M${f1((x + dx) * S)} ${f1((y + dy) * S)}h0`;
          }
        } else {
          const r = 0.04 + R2() * 0.05;
          if (!free(x, y, r)) continue;
          occ.add(x, y, r);
          stoneD += blobD(stonePts(x, y, r, 5 + Math.floor(R2() * 2), R2, 0.35), S);
        }
      }
    }
    // cracks
    const R3 = rng(seed, 'cracks');
    let area = 0;
    for (let y = 0.5; y < H; y++) for (let x = 0.5; x < W; x++) if (F.at(x, y) < 0) area++;
    const nCr = Math.round((area / 22) * Math.min(rub, 2));
    for (let n = 0, tries = 0; n < nCr && tries < nCr * 30; tries++) {
      let x = R3() * W, y = R3() * H;
      if (F.at(x, y) > -0.7 || !free(x, y, 0.4)) continue;
      n++;
      let a = R3() * Math.PI * 2;
      const pts = [[x, y]];
      const steps = 3 + Math.floor(R3() * 4);
      const branch = [];
      for (let k = 0; k < steps; k++) {
        a += (R3() - 0.5) * 1.1;
        const l = 0.12 + R3() * 0.16;
        const nx = x + Math.cos(a) * l, ny = y + Math.sin(a) * l;
        if (F.at(nx, ny) > -0.25 || !free(nx, ny, 0.1)) break;
        x = nx;
        y = ny;
        pts.push([x, y]);
        if (k > 0 && R3() < 0.3) branch.push([x, y, a + (R3() < 0.5 ? 1 : -1) * (0.5 + R3() * 0.6)]);
      }
      if (pts.length < 2) continue;
      crackD += polyD(pts, false, S);
      for (const [bx, by, ba] of branch) {
        const l = 0.1 + R3() * 0.15;
        crackD += `M${f1(bx * S)} ${f1(by * S)}l${f1(Math.cos(ba) * l * S)} ${f1(Math.sin(ba) * l * S)}`;
      }
      for (const q of pts) occ.add(q[0], q[1], 0.1);
    }
  }

  // --- features
  const used = new Set();
  let featOut = '';
  for (const f of s.features) {
    if (f.dmOnly && !dm) continue;
    const tr = `translate(${f1(f.at[0] * S)} ${f1(f.at[1] * S)})${f.rot ? ` rotate(${f2(f.rot)})` : ''}`;
    if (f.kind === 'secret') {
      featOut += `<g transform="${tr}"><text x="0" y="0" font-size="${f1(0.7 * S * f.scale)}" ${TEXT} stroke="#fff" stroke-width="${lw(4)}" paint-order="stroke">S</text></g>`;
      continue;
    }
    const a = ASSETS[f.kind];
    if (!a) {
      featOut += `<g transform="${tr}" fill="#fff" stroke="${INK}" stroke-width="${lw(2)}"><circle r="${f1(0.3 * S * f.scale)}"/><path d="M${f1(-0.15 * S)} ${f1(-0.15 * S)}l${f1(0.3 * S)} ${f1(0.3 * S)}m0 ${f1(-0.3 * S)}l${f1(-0.3 * S)} ${f1(0.3 * S)}"/></g>`;
      continue;
    }
    used.add(f.kind);
    const k = (S * f.scale) / 100;
    featOut += `<use href="#cm-${f.kind}" transform="${tr} scale(${f2(k * 1000) / 1000}) translate(${-50 * a.w} ${-50 * a.h})"/>`;
  }

  // --- DM layer
  let dmOut = '';
  if (dm) {
    for (const c of s.chambers) {
      if (c.label === undefined || c.label === null || c.label === '') continue;
      const r = 0.42 * S;
      dmOut += `<g transform="translate(${f1(c.at[0] * S)} ${f1(c.at[1] * S)})"><circle r="${f1(r)}" fill="#fff" stroke="${INK}" stroke-width="${lw(2.5)}"/><text font-size="${f1(String(c.label).length > 2 ? 0.3 * S : 0.46 * S)}" ${TEXT}>${esc(c.label)}</text></g>`;
    }
    for (const f of s.features) {
      if (f.label === undefined || f.label === null || f.label === '') continue;
      const a = ASSETS[f.kind] || { w: 1, h: 1 };
      const o = 0.38 * f.scale * Math.max(a.w, a.h);
      const r = 0.24 * S;
      dmOut += `<g transform="translate(${f1((f.at[0] + o) * S)} ${f1((f.at[1] - o) * S)})"><circle r="${f1(r)}" fill="#fff" stroke="${INK}" stroke-width="${lw(1.6)}"/><text font-size="${f1(String(f.label).length > 1 ? 0.2 * S : 0.3 * S)}" ${TEXT}>${esc(f.label)}</text></g>`;
    }
  }

  // --- grid
  let gridOut = '';
  if (showGrid) {
    const w = W * S, h = H * S;
    let g = '';
    for (let i = 0; i <= W; i++) g += `<line x1="${f1(i * S)}" y1="0" x2="${f1(i * S)}" y2="${f1(h)}"/>`;
    for (let j = 0; j <= H; j++) g += `<line x1="0" y1="${f1(j * S)}" x2="${f1(w)}" y2="${f1(j * S)}"/>`;
    gridOut = `<g id="grid" clip-path="url(#cm-floor)" stroke="${INK}" stroke-opacity="0.25" stroke-width="${lw(1)}">${g}</g>`;
  }

  // --- assemble
  const defs = [...used].map((k) => `<g id="cm-${k}">${ASSETS[k].svg}</g>`).join('');
  const w = W * S, h = H * S;
  const o = [];
  o.push(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${f1(w)} ${f1(h)}" width="${f1(w)}" height="${f1(h)}">`);
  o.push(`<title>${esc(s.name)}</title>`);
  o.push(`<defs><clipPath id="cm-floor"><path d="${floorD}" clip-rule="evenodd"/></clipPath>${defs}</defs>`);
  o.push(`<rect width="${f1(w)}" height="${f1(h)}" fill="#fff"/>`);
  o.push(`<g id="rock" fill="none" stroke="${INK}" stroke-linecap="round" stroke-linejoin="round">`);
  o.push(`<path d="${hatchD}" stroke-width="${lw(1.15)}"/>`);
  o.push(`<path d="${depthD}" stroke-width="${lw(1.2)}"/>`);
  o.push(`</g>`);
  o.push(`<path id="floor" d="${floorD}" fill="#fff" fill-rule="evenodd"/>`);
  o.push(`<g id="details" fill="none" stroke="${INK}" stroke-linecap="round" stroke-linejoin="round">`);
  if (crackD) o.push(`<path d="${crackD}" stroke-width="${lw(0.9)}"/>`);
  if (dotD) o.push(`<path d="${dotD}" stroke-width="${lw(2.2)}"/>`);
  if (stoneD) o.push(`<path d="${stoneD}" fill="#fff" stroke-width="${lw(1.1)}"/>`);
  o.push(`</g>`);
  if (P) {
    o.push(`<g id="pools" clip-path="url(#cm-floor)" fill="none" stroke="${INK}" stroke-linecap="round" stroke-linejoin="round">`);
    o.push(`<path d="${poolFill}" fill="#fff"/>${poolOut}</g>`);
  }
  if (gridOut) o.push(gridOut);
  o.push(`<path id="wall" d="${wallD}" fill="${INK}" fill-rule="nonzero"/>`);
  if (featOut) o.push(`<g id="features">${featOut}</g>`);
  if (dmOut) o.push(`<g id="dm">${dmOut}</g>`);
  o.push(`</svg>`);
  return o.join('\n') + '\n';
}

const TEXT = `text-anchor="middle" dominant-baseline="central" font-family="Georgia, 'Times New Roman', serif" font-weight="bold" fill="#000"`;

// ---------------------------------------------------------------- assets
// Each asset: inner markup in a box of 100 units per cell (w*100 by h*100), black ink on white.

const A = (...parts) => parts.join('');
const ST = (sw = 3) => `fill="#fff" stroke="#000" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round"`;
const blob = (cx, cy, r, n, key, jit = 0.28) => `<path d="${blobD(stonePts(cx, cy, r, n, rng('asset', key), jit), 1, f1)}"/>`;
const circ = (cx, cy, r, extra = '') => `<circle cx="${f1(cx)}" cy="${f1(cy)}" r="${f1(r)}"${extra}/>`;
const line = (pts) => `<path d="${polyD(pts, false, 1)}" fill="none"/>`;
const rect = (x, y, w, h, rx = 0, extra = '') => `<rect x="${x}" y="${y}" width="${w}" height="${h}"${rx ? ` rx="${rx}"` : ''}${extra}/>`;
const g = (attrs, inner) => `<g ${attrs}>${inner}</g>`;
const BLK = ' fill="#000"';

function polar(cx, cy, r, a) {
  return [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
}

// Outline-by-layering: draw the shapes in black a bit fatter, then in white on top.
function layered(shapes, o = 3) {
  const black = shapes(o, '#000'), white = shapes(0, '#fff');
  return black + white;
}

function bone(x1, y1, x2, y2, w) {
  return (o, col) => {
    const dx = x2 - x1, dy = y2 - y1, l = Math.hypot(dx, dy), nx = -dy / l, ny = dx / l;
    const k = w * 0.55;
    let s = `<path d="M${f1(x1)} ${f1(y1)}L${f1(x2)} ${f1(y2)}" stroke="${col}" stroke-width="${f1(w + 2 * o)}" stroke-linecap="butt" fill="none"/>`;
    for (const [x, y] of [[x1, y1], [x2, y2]])
      for (const sg of [1, -1]) s += circ(x + nx * k * sg, y + ny * k * sg, w * 0.62 + o, ` fill="${col}"`);
    return s;
  };
}

function stairsSvg() {
  // 1 x 2: steps rising toward -y (top), with an arrow pointing up.
  let s = rect(10, 4, 80, 192, 2);
  let y = 190;
  const ys = [];
  for (let k = 0; k < 9; k++) {
    ys.push(y);
    y -= 22 - k * 0.9;
  }
  s += ys.map((yy) => line([[10, yy], [90, yy]])).join('');
  s += line([[10, 4], [10, 196]]).replace('fill="none"', 'fill="none" stroke-width="6"');
  s += line([[90, 4], [90, 196]]).replace('fill="none"', 'fill="none" stroke-width="6"');
  s += `<path d="M50 150L50 40M38 54L50 38L62 54" fill="none" stroke-width="3.5"/>`;
  return g(ST(3), s);
}

function webSvg() {
  const r = rng('asset', 'web');
  const n = 9;
  const angs = [];
  for (let i = 0; i < n; i++) angs.push(((i + (r() - 0.5) * 0.4) / n) * Math.PI * 2);
  let s = '';
  for (const a of angs) s += line([[50, 50], polar(50, 50, 47 - r() * 6, a)]);
  for (const rad of [9, 17, 26, 35, 43]) {
    let d = '';
    for (let i = 0; i <= n; i++) {
      const a = angs[i % n], b = angs[(i + 1) % n];
      const p = polar(50, 50, rad, a), q = polar(50, 50, rad, b + (i + 1 === n ? Math.PI * 2 : 0));
      const mid = polar(50, 50, rad * 0.86, (a + b + (i + 1 === n ? Math.PI * 2 : 0)) / 2);
      if (i === 0) d += `M${f1(p[0])} ${f1(p[1])}`;
      if (i < n) d += `Q${f1(mid[0])} ${f1(mid[1])} ${f1(q[0])} ${f1(q[1])}`;
    }
    s += `<path d="${d}" fill="none"/>`;
  }
  return g(ST(1.6), s);
}

function campfireSvg() {
  let s = '';
  for (let i = 0; i < 9; i++) {
    const [x, y] = polar(50, 50, 37, (i / 9) * Math.PI * 2 + 0.2);
    s += blob(x, y, 8.5, 6, 'cf' + i, 0.35);
  }
  s += layered((o, col) => {
    let t = '';
    for (const [a, b] of [[[24, 34], [76, 66]], [[26, 68], [74, 32]]])
      t += `<path d="M${a[0]} ${a[1]}L${b[0]} ${b[1]}" stroke="${col}" stroke-width="${10 + 2 * o}" fill="none" stroke-linecap="round"/>`;
    return t;
  });
  s += line([[30, 37.5], [44, 46]]) + line([[58, 54.5], [70, 61]]) + line([[56, 44], [68, 37]]);
  // flame: outer and inner tongues
  s += `<path d="M50 70C36 66 34 52 42 42C42 50 46 50 46 46C46 38 52 32 54 24C58 34 66 40 62 54C62 50 64 48 66 46C68 58 62 68 50 70Z"/>`;
  s += `<path d="M50 63C44 61 43 54 47 49C48 53 50 53 51 50C52 46 55 43 55 40C59 47 60 52 57 58C55 61 53 63 50 63Z" fill="#000"/>`;
  return g(ST(2.6), s);
}

function boneSvg() {
  return g(ST(3), layered(bone(22, 30, 74, 62, 7), 2.4) + layered(bone(28, 76, 70, 70, 6), 2.4) + layered(bone(66, 18, 80, 40, 5), 2.2) +
    blob(30, 52, 4, 5, 'bf1') + blob(52, 86, 3.5, 5, 'bf2') + blob(84, 74, 3, 5, 'bf3'));
}

function skullSvg() {
  // 1/2 x 1/2: box 50 x 50
  const s = layered((o, col) =>
    `<ellipse cx="25" cy="21" rx="${16 + o}" ry="${15 + o}" fill="${col}"/>` +
    `<rect x="${15 - o}" y="${27 - o}" width="${20 + 2 * o}" height="${16 + 2 * o}" rx="5" fill="${col}"/>`, 2.4);
  return g(ST(2.2), s + `<ellipse cx="19" cy="24" rx="4.5" ry="5"${BLK} stroke="none"/><ellipse cx="31" cy="24" rx="4.5" ry="5"${BLK} stroke="none"/>` +
    `<path d="M25 29L22.5 34H27.5Z"${BLK} stroke-width="1"/>` + line([[19, 37], [19, 42]]) + line([[23, 37.5], [23, 42.5]]) + line([[27, 37.5], [27, 42.5]]) + line([[31, 37], [31, 42]]) + line([[16, 37], [34, 37]]));
}

function mushroomSvg() {
  let s = '';
  for (const [cx, cy, r, k] of [[36, 40, 20, 'm1'], [68, 56, 15, 'm2'], [38, 74, 11, 'm3'], [70, 26, 8, 'm4']]) {
    s += blob(cx, cy, r, 9, k, 0.12);
    for (let i = 0; i < 10; i++) {
      const a = (i / 10) * Math.PI * 2 + r;
      s += `<path d="M${f1(cx + Math.cos(a) * r * 0.35)} ${f1(cy + Math.sin(a) * r * 0.35)}L${f1(cx + Math.cos(a) * r * 0.78)} ${f1(cy + Math.sin(a) * r * 0.78)}" stroke-width="1.4" fill="none"/>`;
    }
    s += circ(cx, cy, r * 0.22);
  }
  return g(ST(2.6), s);
}

function rubbleSvg() {
  const r = rng('asset', 'rubble');
  let s = '';
  const placed = [];
  for (let t = 0; t < 200 && placed.length < 13; t++) {
    const rad = 3 + r() * 7.5;
    const x = 12 + r() * 76, y = 12 + r() * 76;
    if (placed.some(([px, py, pr]) => Math.hypot(px - x, py - y) < pr + rad + 2)) continue;
    placed.push([x, y, rad]);
    s += blob(x, y, rad, 5 + Math.floor(r() * 3), 'rb' + placed.length, 0.4);
  }
  return g(ST(2.2), s);
}

function barrelSvg() {
  let s = circ(50, 50, 38) + circ(50, 50, 32, ' stroke-width="2"');
  for (const x of [34, 42, 50, 58, 66]) {
    const h = Math.sqrt(32 * 32 - (x - 50) ** 2);
    s += line([[x, 50 - h], [x, 50 + h]]).replace('fill="none"', 'fill="none" stroke-width="1.4"');
  }
  s += circ(50, 50, 4.5, BLK);
  return g(ST(3), s);
}

function pillarSvg() {
  let s = circ(50, 50, 42) + circ(50, 50, 34, ' stroke-width="2"');
  for (let k = -5; k <= 5; k++) {
    const c = k * 9; // diagonal lines x - y = c, clipped to radius 30
    const rr = 30;
    const half = Math.sqrt(Math.max(0, rr * rr - (c * c) / 2));
    if (half < 3) continue;
    const mx = 50 + c / 2, my = 50 - c / 2;
    const ux = Math.SQRT1_2, uy = Math.SQRT1_2;
    s += line([[mx - ux * half, my - uy * half], [mx + ux * half, my + uy * half]]).replace('fill="none"', 'fill="none" stroke-width="1.6"');
  }
  return g(ST(3.2), s);
}

function stalagmiteSvg() {
  let s = blob(50, 52, 40, 12, 'st1', 0.3) + blob(53, 49, 26, 10, 'st2', 0.32) + blob(55, 47, 13, 8, 'st3', 0.35);
  for (let i = 0; i < 14; i++) {
    const a = (i / 14) * Math.PI * 2 + 0.3;
    s += line([polar(55, 47, 15.5, a), polar(55, 47, 19 + (i % 3) * 1.5, a)]).replace('fill="none"', 'fill="none" stroke-width="1.4"');
    if (i % 2) s += line([polar(52, 50, 30, a + 0.2), polar(51, 51, 35, a + 0.2)]).replace('fill="none"', 'fill="none" stroke-width="1.4"');
  }
  s += `<path d="${blobD(stonePts(56, 46, 5.5, 6, rng('asset', 'tip'), 0.4), 1, f1)}" fill="#000"/>`;
  return g(ST(2.8), s);
}

export const ASSETS = {
  boulder: { w: 1, h: 1, svg: g(ST(3), blob(50, 52, 40, 9, 'boulder', 0.22) + line([[24, 44], [42, 36], [58, 42], [70, 34]]) + line([[42, 36], [46, 58], [40, 72]]) + line([[58, 42], [66, 62]]) +
    [[62, 70, 68, 78], [70, 66, 77, 73], [52, 74, 56, 82]].map(([a, b, c, d]) => line([[a, b], [c, d]])).join('').replace(/fill="none"/g, 'fill="none" stroke-width="1.6"')) },
  rocks: { w: 1, h: 1, svg: g(ST(2.8), blob(34, 40, 19, 8, 'r1') + blob(66, 34, 14, 7, 'r2') + blob(58, 68, 17, 8, 'r3') + blob(24, 72, 7, 6, 'r4') + blob(84, 60, 6, 5, 'r5') +
    '<path d="M24 42Q32 34 42 36M50 72Q56 64 66 66M60 36Q66 32 72 36" fill="none" stroke-width="1.8"/>') },
  rubble: { w: 1, h: 1, svg: rubbleSvg() },
  stalagmite: { w: 1, h: 1, svg: stalagmiteSvg() },
  pillar: { w: 1, h: 1, svg: pillarSvg() },
  mushrooms: { w: 1, h: 1, svg: mushroomSvg() },
  bones: { w: 1, h: 1, svg: boneSvg() },
  skull: { w: 0.5, h: 0.5, svg: skullSvg() },
  campfire: { w: 1, h: 1, svg: campfireSvg() },
  bedroll: { w: 1, h: 2, svg: g(ST(3), rect(20, 10, 60, 180, 12) + rect(28, 18, 44, 30, 9) + line([[24, 70], [76, 70]]) +
    '<path d="M24 70L24 86Q50 78 76 86L76 70"/>' + line([[34, 100], [34, 182]]).replace('fill="none"', 'fill="none" stroke-dasharray="5 6" stroke-width="1.6"') +
    line([[66, 100], [66, 182]]).replace('fill="none"', 'fill="none" stroke-dasharray="5 6" stroke-width="1.6"') + line([[36, 28], [52, 26]]) + line([[54, 38], [64, 36]])) },
  chest: { w: 1, h: 1, svg: g(ST(3), rect(12, 24, 76, 52, 4) + rect(12, 24, 76, 15, 3) + rect(26, 24, 9, 52, 0, ' stroke-width="2"') + rect(65, 24, 9, 52, 0, ' stroke-width="2"') +
    rect(44, 66, 12, 12, 2, BLK) + circ(50, 71, 2, ' fill="#fff" stroke="none"') + [[16, 44], [84, 44], [16, 72], [84, 72]].map(([x, y]) => circ(x, y, 1.6, BLK)).join('')) },
  crate: { w: 1, h: 1, svg: g(ST(3), rect(14, 14, 72, 72, 2) + rect(22, 22, 56, 56, 0, ' stroke-width="2"') + '<path d="M22 70L70 22M30 78L78 30" fill="none" stroke-width="2"/>' +
    line([[22, 41], [32, 41]]) + line([[68, 59], [78, 59]]) + [[18, 18], [82, 18], [18, 82], [82, 82]].map(([x, y]) => circ(x, y, 1.5, BLK)).join('')) },
  barrel: { w: 1, h: 1, svg: barrelSvg() },
  table: { w: 2, h: 1, svg: g(ST(3), rect(8, 14, 184, 72, 4) + [34, 50, 66].map((y) => line([[8, y], [192, y]]).replace('fill="none"', 'fill="none" stroke-width="1.6"')).join('') +
    line([[60, 14], [60, 34]]) + line([[120, 34], [120, 50]]) + line([[84, 50], [84, 66]]) + line([[150, 66], [150, 86]]) +
    circ(150, 42, 10) + circ(150, 42, 6, ' stroke-width="1.4"') + '<path d="M44 66h14v10h-14z" stroke-width="2"/>' + circ(30, 30, 5, ' stroke-width="2"')) },
  chair: { w: 0.5, h: 0.5, svg: g(ST(2.4), rect(11, 14, 28, 26, 3) + rect(9, 8, 32, 8, 2, BLK)) },
  torch: { w: 0.5, h: 0.5, svg: g(ST(2), rect(18, 38, 14, 9, 1, BLK) + line([[25, 38], [25, 26]]).replace('fill="none"', 'fill="none" stroke-width="4"') +
    '<path d="M25 26C19 24 18 17 22 12C22 15 24 16 24 14C24 9 26 6 28 3C30 9 33 14 31 20C30 24 28 26 25 26Z"/>' +
    [0, 1, 2, 3, 4].map((i) => { const a = Math.PI * (1.05 + i * 0.225); return line([polar(25, 16, 16, a), polar(25, 16, 21, a)]); }).join('').replace(/fill="none"/g, 'fill="none" stroke-width="1.4"')) },
  stairs: { w: 1, h: 2, svg: stairsSvg() },
  door: { w: 1, h: 0.5, svg: g(ST(2.6), rect(0, 10, 12, 30, 1, BLK) + rect(88, 10, 12, 30, 1, BLK) + rect(12, 16, 76, 18, 1) + [31, 50, 69].map((x) => line([[x, 16], [x, 34]])).join('').replace(/fill="none"/g, 'fill="none" stroke-width="1.4"') +
    rect(15, 15, 8, 4, 0, BLK) + rect(15, 31, 8, 4, 0, BLK) + circ(80, 25, 2.4, BLK)) },
  ladder: { w: 1, h: 2, svg: g(ST(3), line([[30, 6], [30, 194]]).replace('fill="none"', 'fill="none" stroke-width="5"') + line([[70, 6], [70, 194]]).replace('fill="none"', 'fill="none" stroke-width="5"') +
    Array.from({ length: 10 }, (_, i) => line([[30, 16 + i * 19], [70, 16 + i * 19]])).join('')) },
  web: { w: 1, h: 1, svg: webSvg() },
  trap: { w: 1, h: 1, svg: g(ST(2.6), rect(14, 14, 72, 72, 0, ' fill="none" stroke-dasharray="9 6"') + line([[26, 26], [74, 74]]) + line([[74, 26], [26, 74]]) +
    [[34, 50], [66, 50], [50, 34], [50, 66]].map(([x, y]) => circ(x, y, 2.6, BLK)).join('')) },
  altar: { w: 2, h: 1, svg: g(ST(3), rect(8, 16, 184, 70, 3) + rect(20, 26, 160, 50, 2, ' stroke-width="2"') + line([[8, 86], [20, 76]]) + line([[192, 86], [180, 76]]) + line([[8, 16], [20, 26]]) + line([[192, 16], [180, 26]]) +
    circ(40, 51, 7) + circ(40, 51, 2.5, BLK) + circ(160, 51, 7) + circ(160, 51, 2.5, BLK) + circ(100, 51, 14, ' stroke-width="2"') + '<path d="M100 39L110 58H90Z" fill="none" stroke-width="2"/>') },
  statue: { w: 1, h: 1, svg: g(ST(3), rect(12, 12, 76, 76, 2) + rect(20, 20, 60, 60, 0, ' stroke-width="1.6"') + line([[12, 12], [20, 20]]) + line([[88, 12], [80, 20]]) + line([[12, 88], [20, 80]]) + line([[88, 88], [80, 80]]) +
    rect(28, 42, 44, 18, 9) + '<path d="M36 60L38 70H62L64 60" stroke-width="2"/>' + circ(50, 49, 10) + '<path d="M44 46Q50 42 56 46" fill="none" stroke-width="1.4"/>') },
};

export function assetSvg(name) {
  const a = ASSETS[name];
  if (!a) throw new Error(`unknown asset "${name}"`);
  const w = a.w * 100, h = a.h * 100;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">\n<title>${name}</title>\n${a.svg}\n</svg>\n`;
}
