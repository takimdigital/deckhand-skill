/**
 * catalog.mjs — deterministic candidate ranking. Same inputs -> same order, always.
 * Personal library items (r = "mine") rank first; base mismatches are hidden AND counted.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { COMPATIBLE, kindOf } from './slots.mjs';
import { depInstalled } from './project.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const SKILL_DIR = path.resolve(HERE, '..', '..');

export function libraryDir() {
  return process.env.DECKHAND_LIBRARY || path.join(process.env.DECKHAND_HOME || path.join(os.homedir(), '.deckhand'), 'library');
}

export function loadCatalog() {
  const main = JSON.parse(fs.readFileSync(path.join(SKILL_DIR, 'data', 'components.index.json'), 'utf8'));
  let items = main.items;
  // the owner's vetted registries (`tryon registry add`) — after their own library, before the shipped catalog
  const extra = path.join(path.dirname(libraryDir()), 'catalog');
  if (fs.existsSync(extra)) {
    for (const f of fs.readdirSync(extra).filter((x) => x.endsWith('.json')).sort()) {
      try { items = JSON.parse(fs.readFileSync(path.join(extra, f), 'utf8')).items.concat(items); } catch { /* skip a broken file */ }
    }
  }
  const mine = path.join(libraryDir(), 'components.index.json');
  if (fs.existsSync(mine)) {
    try { items = JSON.parse(fs.readFileSync(mine, 'utf8')).items.concat(items); } catch { /* a broken personal index never blocks the catalog */ }
  }
  // the fit check's verdicts (tryon/lib/fitcheck.mjs): rank() hides a design the engine cannot stage
  const verdicts = loadVerdicts();
  return verdicts.size ? items.map((it) => (verdicts.has(it.id) ? { ...it, check: verdicts.get(it.id).v } : it)) : items;
}

/** Where fit-check verdicts live: shipped with the skill, and the owner's own runs (they win). */
export const shippedChecksDir = () => path.join(SKILL_DIR, 'data', 'checks');
export const localChecksDir = () => path.join(path.dirname(libraryDir()), 'catalog', 'checks');

/** id -> {v, why?, needs?}: shipped first, the owner's own runs over them. A broken file never blocks the catalog. */
export function loadVerdicts() {
  const out = new Map();
  for (const dir of [shippedChecksDir(), localChecksDir()]) {
    let files = [];
    try { files = fs.readdirSync(dir).filter((f) => f.endsWith('.json')).sort(); } catch { continue; }
    for (const f of files) {
      try { for (const [id, v] of Object.entries(JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')).verdicts || {})) out.set(id, v); } catch { /* skip */ }
    }
  }
  return out;
}

function baseScore(projectBase, itemBase) {
  if (itemBase === 'any' || !itemBase) return 20;
  if (projectBase === 'none') return itemBase === 'radix' ? 25 : 10;
  if (projectBase === itemBase) return 30;
  return null;                                   // hidden: a Radix project never gets Base UI code
}

export function rank(items, { slot, prof, exclude = [], registry = null, includeBroken = false }) {
  const cousins = COMPATIBLE[slot] || [slot];
  const out = [];
  let hidden = 0;
  let broken = 0;
  for (const it of items) {
    if (exclude.includes(it.id)) continue;
    if (registry && it.r !== registry) continue;
    const exact = it.slot === slot;
    if (!exact && !cousins.includes(it.slot)) continue;
    // the fit check staged it and the engine could not: never offered (a flag report's `--only` still reaches it)
    if (it.check === 'broken' && !includeBroken) { broken++; continue; }
    // the project's own primitive is not an alternative to itself
    if (it.kind === 'ui' && (it.r === 'shadcn' || it.r === 'basecn') && prof.ui && prof.ui[it.n]) continue;
    const b = baseScore(prof.base, it.base);
    if (b === null) { hidden++; continue; }
    let s = (exact ? 100 : 40) + b;
    if (it.r === 'mine' && exact) s += 60;                          // my saved hero ranks first for a hero, not for a CTA
    if (kindOf(slot) === 'block' && it.r === 'tailark-oss') s += 5;
    const missing = (it.deps || []).filter((d) => !depInstalled(prof, d));
    s -= missing.length * 6;
    if (it.check === 'refused') s -= 30;                             // the fit gate refused it for this kind: last
    else if (it.check === 'fits') s += 3;
    out.push({ ...it, score: s, missing });
  }
  out.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
  // diversity: round-robin over registry+kit groups so a batch shows different design languages
  const group = kitOf;
  const buckets = new Map();
  for (const x of out) { const g = group(x); if (!buckets.has(g)) buckets.set(g, []); buckets.get(g).push(x); }
  const order = [...buckets.keys()].sort((a, b) => buckets.get(b)[0].score - buckets.get(a)[0].score || a.localeCompare(b));
  const mixed = [];
  for (let i = 0; mixed.length < out.length; i++) for (const g of order) if (buckets.get(g)[i]) mixed.push(buckets.get(g)[i]);
  return { items: mixed, hidden, broken };
}

/** A design family: one Tailark kit (dusk / mist / veil) or one registry. */
export const kitOf = (x) => x.r + ':' + (x.r === 'tailark-oss' ? x.n.split('-')[0] : '');

export function slotsSummary(items, prof) {
  const counts = {};
  for (const it of items) {
    if (baseScore(prof.base, it.base) === null) continue;
    counts[it.slot] = (counts[it.slot] || 0) + 1;
  }
  return counts;
}
