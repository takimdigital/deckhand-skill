/**
 * library.mjs — the owner's personal component pool ("mine"), shared by try-on and `dh`.
 *
 *   <library>/components/<name>/...        the files, exactly as kept (the owner's version)
 *   <library>/components.index.json        catalog rows (r = "mine"), ranked first in every query
 *
 * Saving refuses what cannot be honoured later: no recorded licence, or a credential-shaped string.
 */
import fs from 'node:fs';
import path from 'node:path';
import { libraryDir } from './catalog.mjs';
import { detectProject } from './project.mjs';
import { loadSession } from './engine.mjs';
import { kindOf } from './slots.mjs';

// one secret policy (data/secrets.json, shared with dh verify / harvest / log redaction); strict: no JWT, no test keys either
const POLICY = JSON.parse(fs.readFileSync(new URL('../../data/secrets.json', import.meta.url), 'utf8'));
const SECRET = new RegExp([...POLICY.values, ...POLICY.strict_extra].map((v) => `(?:${v.rx})`).join('|'));

function indexPath() { return path.join(libraryDir(), 'components.index.json'); }
export function readIndex() {
  try { return JSON.parse(fs.readFileSync(indexPath(), 'utf8')); } catch { return { version: 2, items: [] }; }
}
function writeIndex(doc) {
  fs.mkdirSync(libraryDir(), { recursive: true });
  doc.count = doc.items.length;
  fs.writeFileSync(indexPath(), JSON.stringify(doc, null, 1) + '\n');
}

/** Save a directory of component files as a library item. */
export function saveDir({ dir, entry, name, slot, base = 'any', lic, source, title, deps = [] }) {
  if (!lic) throw Object.assign(new Error('NO_LICENCE: a component without a recorded licence cannot be saved'), { code: 'NO_LICENCE' });
  const clean = String(name).toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-|-$/g, '').slice(0, 63);
  if (clean.length < 2) throw Object.assign(new Error('BAD_NAME'), { code: 'BAD_NAME' });
  for (const f of fs.readdirSync(dir)) {
    const text = fs.readFileSync(path.join(dir, f), 'utf8');
    if (SECRET.test(text)) throw Object.assign(new Error('CREDENTIAL_SHAPED_VALUE in ' + f + ' — nothing saved'), { code: 'CREDENTIAL' });
  }
  const dest = path.join(libraryDir(), 'components', clean);
  fs.rmSync(dest, { recursive: true, force: true });
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.cpSync(dir, dest, { recursive: true });
  const doc = readIndex();
  doc.items = doc.items.filter((i) => i.n !== clean);
  const item = { id: `mine/${clean}@${base}`, r: 'mine', n: clean, base, slot, kind: kindOf(slot), t: title || clean,
    deps, local: clean, entry: path.basename(entry), lic, source: source || null, savedAt: new Date().toISOString() };
  doc.items.unshift(item);
  writeIndex(doc);
  return item;
}

export function saveToLibrary(rootIn, sessionId, { name } = {}) {
  const prof = detectProject(rootIn);
  const s = loadSession(prof.root, sessionId);
  if (s.state !== 'kept') throw Object.assign(new Error('NOT_KEPT: keep a variant first, then save it'), { code: 'NOT_KEPT' });
  const v = s.variants.find((x) => x.idx === s.chosen);
  const item = saveDir({
    dir: path.join(prof.root, s.final.dir), entry: s.final.entry, name: name || `${s.slot}-${v.n}`, slot: s.slot,
    base: prof.base === 'none' ? 'any' : prof.base, lic: v.lic, source: v.sourceUrl, title: `${v.t} (mine)`, deps: v.deps,
  });
  return { saved: item.id, library: libraryDir(), rankFirst: true };
}

export function listLibrary() { return readIndex().items; }

export function removeFromLibrary(name) {
  const doc = readIndex();
  const before = doc.items.length;
  doc.items = doc.items.filter((i) => i.n !== name);
  if (doc.items.length === before) return { removed: false };
  const dir = path.join(libraryDir(), 'components', name);
  const arch = path.join(libraryDir(), '_archive', name + '-' + Date.now());
  if (fs.existsSync(dir)) { fs.mkdirSync(path.dirname(arch), { recursive: true }); fs.renameSync(dir, arch); }
  writeIndex(doc);
  return { removed: true, archived: arch };
}
