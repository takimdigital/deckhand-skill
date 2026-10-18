#!/usr/bin/env node
/**
 * catalog-build.mjs — (re)build data/components.index.json from the licensed registries.
 * Maintainer tool; owners never need it (the index ships with the skill).
 *
 *   node tryon/catalog-build.mjs [--snapshots <dir>] [--out data/components.index.json] [--only id,id]
 *
 * --only rebuilds just those registries and keeps every other item of the current index (a registry whose site
 * is unreachable from here is not dropped). A registry's `index_mirror` (its registry.json committed on GitHub)
 * is read when its site is not.
 *
 * Sources (data/registries.json): tailark-oss is read from its MIT GitHub source (the registry
 * definitions are TypeScript, parsed with the vendored AST parser — no regex over code); every
 * shadcn-schema registry is read from its live registry.json, or from --snapshots/<id>@<style>.json.
 * Only registries whose licence is MIT/Apache-2.0 are indexed; `refused` entries never are.
 */
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { TAILARK_CATEGORY, slotFromName, kindOf } from './lib/slots.mjs';
import { mapShadcnItems, navbarsFromHeroes } from './lib/regmap.mjs';

const require = createRequire(import.meta.url);
const { parse, walk } = require('./lib/ast.cjs');
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SKILL = path.resolve(HERE, '..');
const OK_LICENSES = new Set(Object.keys(JSON.parse(fs.readFileSync(path.join(SKILL, 'data', 'licenses.json'), 'utf8')).accepted));

const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf('--' + k); return i >= 0 ? args[i + 1] : d; };
const SNAP = opt('snapshots', null);
const OUT = path.resolve(opt('out', path.join(SKILL, 'data', 'components.index.json')));
const ONLY = opt('only', null) ? new Set(opt('only').split(',')) : null;

async function get(url) {
  const r = await fetch(url, { headers: { 'user-agent': 'deckhand-catalog/2' } });
  if (!r.ok) throw new Error(url + ' -> HTTP ' + r.status);
  return r.text();
}

/** Evaluate the literal parts of a helper call argument: strings, numbers, arrays, nested objects, and
 *  the helper calls ui("x") / core("x") / local("x") / motionPrimitive("x") as tagged strings. */
function lit(node, helpers) {
  if (!node) return undefined;
  switch (node.type) {
    case 'StringLiteral': return node.value;
    case 'NumericLiteral': return node.value;
    case 'BooleanLiteral': return node.value;
    case 'ArrayExpression': return node.elements.map((e) => lit(e, helpers));
    case 'ObjectExpression': {
      const o = {};
      for (const p of node.properties) {
        if (p.type !== 'ObjectProperty') continue;
        const k = p.key.type === 'Identifier' ? p.key.name : p.key.value;
        o[k] = lit(p.value, helpers);
      }
      return o;
    }
    case 'CallExpression': {
      const fn = node.callee.type === 'Identifier' ? node.callee.name : null;
      const a = node.arguments.map((x) => lit(x, helpers));
      return helpers[fn] ? helpers[fn](...a) : undefined;
    }
    default: return undefined;
  }
}

const NUM = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17, eighteen: 18, nineteen: 19, twenty: 20 };

async function tailark(reg) {
  const out = [];
  for (const [base, jsonTpl] of Object.entries(reg.bases)) {
    const dir = base === 'base-ui' ? 'base' : base;
    for (const kit of reg.kits) {
      const rel = `registry/bases/${dir}/${kit}/_registry.ts`;
      let src;
      try { src = await get(`https://raw.githubusercontent.com/${reg.gh}/${rel}`); } catch (e) { console.error('skip', rel, e.message); continue; }
      const helpers = {
        ui: (n) => `@tailark-oss/${kit}-${n}`, core: (n) => `@tailark-oss/core-${n}`, local: (n) => `@tailark-oss/${kit}-${n}`,
        motionPrimitive: (n) => `@tailark-oss/motion-primitives-${n}`, magicUi: (n) => `@tailark-oss/magic-ui-${n}`,
        shadcn: (n) => `@shadcn/${n}`,
        block: (o) => ({ __block: o }),
      };
      const ast = parse(rel, src);
      walk(ast, (node) => {
        if (node.type !== 'CallExpression' || node.callee.type !== 'Identifier' || node.callee.name !== 'block') return true;
        const o = lit(node.arguments[0], helpers) || {};
        if (!o.category || !o.path) return false;
        const slot = TAILARK_CATEGORY[o.category] || slotFromName(o.category);
        if (!slot) return false;
        const number = NUM[o.variant] ?? o.variant;
        const name = `${kit}-${o.category}-${number}`;
        out.push({
          id: `tailark-oss/${name}@${base}`, r: 'tailark-oss', n: name, base, slot, kind: kindOf(slot),
          t: `${kit[0].toUpperCase() + kit.slice(1)} · ${o.category.replace(/-/g, ' ')} ${number}`,
          deps: o.packageDependencies || [], rdeps: (o.dependencies || []).filter(Boolean),
          gh: `${reg.gh}/registry/bases/${dir}/${o.path}`,
          json: jsonTpl.replace('{name}', name),
          ...(o.meta && o.meta.width ? { w: o.meta.width, h: o.meta.height } : {}),
          lic: reg.license,
        });
        return false;
      });
    }
  }
  return out;
}

function readSnapshot(id, style) {
  if (!SNAP) return null;
  for (const f of [`${id}@${style || 'base-nova'}.json`, `${id}@${style || 'base-nova'}.json.gz`, `${id}.json`]) {
    const p = path.join(SNAP, f);
    if (!fs.existsSync(p)) continue;
    const buf = fs.readFileSync(p);
    return JSON.parse((p.endsWith('.gz') ? zlib.gunzipSync(buf) : buf).toString('utf8'));
  }
  return null;
}

async function shadcnSchema(reg) {
  const out = [];
  const styles = reg.styles ? Object.entries(reg.styles) : [[null, reg.base || 'any']];
  for (const [style, base] of styles) {
    let idx = readSnapshot(reg.id, style);
    for (const u of [reg.index, reg.index_mirror].filter(Boolean)) {
      if (idx) break;
      try { idx = JSON.parse(await get(u.replace('{style}', style))); } catch (e) { console.error('skip', reg.id, style, e.message); }
    }
    if (!idx) continue;
    out.push(...mapShadcnItems(reg, idx, style, base));
  }
  return out;
}

async function main() {
  const regs = JSON.parse(fs.readFileSync(path.join(SKILL, 'data', 'registries.json'), 'utf8'));
  let items = [];
  for (const reg of regs.registries) {
    if (ONLY && !ONLY.has(reg.id)) continue;
    if (!OK_LICENSES.has(reg.license) || reg.status === 'excluded') { console.error('refused', reg.id, reg.license); continue; }
    const got = reg.adapter === 'tailark-oss' ? await tailark(reg) : await shadcnSchema(reg);
    console.error(reg.id, got.length);
    items = items.concat(got);
  }
  items = items.concat(navbarsFromHeroes(items));
  if (ONLY) items = items.concat(JSON.parse(fs.readFileSync(OUT, 'utf8')).items.filter((i) => !ONLY.has(i.r)));
  const seen = new Set();
  items = items.filter((i) => (seen.has(i.id) ? false : (seen.add(i.id), true)));
  items.sort((a, b) => (a.slot + a.r + a.n + a.base).localeCompare(b.slot + b.r + b.n + b.base));
  const doc = { version: 2, built: new Date().toISOString().slice(0, 10), count: items.length, items };
  fs.writeFileSync(OUT, JSON.stringify(doc) + '\n');
  const bySlot = {};
  for (const i of items) bySlot[i.slot] = (bySlot[i.slot] || 0) + 1;
  console.log(JSON.stringify({ ok: true, out: path.relative(process.cwd(), OUT), count: items.length, bySlot }));
}

main().catch((e) => { console.error(e); process.exit(1); });
