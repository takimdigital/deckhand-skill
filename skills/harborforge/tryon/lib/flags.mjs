/**
 * flags.mjs — the owner flags a variant that does not work ("my words are missing", "it shows demo words", "the
 * layout is broken"…) and turns the flags into ONE deterministic Markdown report an AI (or a person) can fix the
 * engine from, for every design of the same shape, not just the one flagged.
 *
 * A flag captures, at the moment it is raised, everything needed to reproduce it offline: where (file:line:col,
 * slot), the design (id, registry, licence, source, deps), what the engine carried and dropped (fit), the owner's
 * element as it was (from the session backup), the design's content slots and staged entry, what the page showed
 * (the overlay's auto-check: missing words, demo words, overflow, broken images, console errors) and the
 * environment (Deckhand version, catalog date, framework, base).
 *
 * State: <project>/.deckhand/tryon/flags.json; reports in .deckhand/tryon/reports/. Both hold the owner's site text,
 * and .deckhand/tryon/ is gitignored: nothing leaves the machine unless the owner sends the report.
 * Same flags -> same report bytes (no clock in it); its name is the hash of its content.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { stateDir, loadSession, TryonError } from './engine.mjs';
import { detectProject } from './project.mjs';
import { extractUnits } from './transplant.mjs';
import { SKILL_DIR } from './catalog.mjs';

const require = createRequire(import.meta.url);
const { parse, findElementAt } = require('./ast.cjs');

/** What the owner can say is wrong (the overlay shows these words; the report groups by them). */
export const REASONS = {
  missing: 'my words, links or images are missing',
  foreign: "it shows words that aren't mine",
  layout: 'the layout is broken',
  mobile: 'it breaks on a phone',
  error: 'the page shows an error',
  'wrong-kind': 'it is not this kind of section',
  style: 'the colours or fonts are off',
  other: 'something else',
};

const flagsFile = (root) => path.join(stateDir(root), 'flags.json');
const clip = (s, n) => { const t = String(s == null ? '' : s); return t.length > n ? t.slice(0, n) + '…' : t; };
const strList = (a, n, len = 160) => (Array.isArray(a) ? a : []).slice(0, n).map((x) => clip(x, len)).filter((x) => x.trim());

function readFlags(root) {
  try { return JSON.parse(fs.readFileSync(flagsFile(root), 'utf8')); } catch { return { version: 1, flags: [] }; }
}
function writeFlags(root, doc) {
  fs.mkdirSync(stateDir(root), { recursive: true });
  fs.writeFileSync(flagsFile(root), JSON.stringify(doc, null, 2));
}

export function listFlags(rootIn) {
  const root = detectProject(rootIn).root;
  return readFlags(root).flags.slice().sort((a, b) => a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id));
}

export const publicFlag = (f) => ({ id: f.id, slot: f.where.slot, file: f.where.file, title: f.variant.title, design: f.variant.id,
  registry: f.variant.registry, reasons: f.reasons, note: f.note, fit: f.variant.fit ? `${f.variant.fit.carried}/${f.variant.fit.of}` : null, createdAt: f.createdAt });

function skillVersion() {
  try { return (/^version:\s*(\S+)/m.exec(fs.readFileSync(path.join(SKILL_DIR, 'SKILL.md'), 'utf8')) || [])[1] || null; } catch { return null; }
}
function catalogBuilt() {
  try { return JSON.parse(fs.readFileSync(path.join(SKILL_DIR, 'data', 'components.index.json'), 'utf8')).built || null; } catch { return null; }
}

/** The owner's element as it was before the try (the session backup), and its content units. */
function ownerElement(root, s) {
  try {
    const code = fs.readFileSync(path.join(root, s.backup), 'utf8').replace(/\r\n/g, '\n');
    const ast = parse(s.file, code);
    const el = findElementAt(ast, code, s.line, s.col);
    if (!el) return { jsx: null, units: [] };
    const u = extractUnits(code, el, ast);
    const units = u.units.map((x) => ({ role: x.role, text: clip(x.text, 200) }))
      .concat(u.images.map((im) => ({ role: 'image', text: clip(im.src, 200) })))
      .concat(u.lists.flatMap((l, i) => l.items.map((it, j) => ({ role: `list ${i + 1} item ${j + 1}`, text: clip(it.units.map((x) => x.text).join(' · '), 200) }))));
    return { jsx: clip(code.slice(el.start, el.end), 8000), units: units.slice(0, 80) };
  } catch { return { jsx: null, units: [] }; }
}

/** The design's content slots as staged: `content.x ?? <demo words>` (what each place shows when the owner has nothing for it). */
export function designSlots(code) {
  const out = new Map();
  for (const m of String(code).matchAll(/content\??\.(\w+)\s*\?\?\s*(?:<span[^>]*data-dh-demo[^>]*>([\s\S]{0,600}?)<\/span>|(["'`])([^"'`]{0,300})\3|<>([\s\S]{0,600}?)<\/>)?/g)) {
    const key = m[1];
    const demo = (m[2] ?? m[4] ?? m[5] ?? '').replace(/<[^>]*>/g, ' ').replace(/\{[^}]*\}/g, ' ').replace(/\s+/g, ' ').trim();
    if (!out.has(key) || (!out.get(key) && demo)) out.set(key, clip(demo, 120));
  }
  return [...out].map(([slot, demo]) => ({ slot, demo })).sort((a, b) => a.slot.localeCompare(b.slot, 'en', { numeric: true }));
}

function cleanAuto(a) {
  if (!a || typeof a !== 'object') return null;
  const n = (x) => (Number.isFinite(Number(x)) ? Math.max(0, Math.min(1e6, Math.round(Number(x)))) : 0);
  return {
    missing: strList(a.missing, 20), foreign: strList(a.foreign, 20), overflow: n(a.overflow), brokenImages: strList(a.brokenImages, 10, 300),
    errors: strList(a.errors, 10, 400), viewport: a.viewport ? { w: n(a.viewport.w), h: n(a.viewport.h) } : null,
  };
}

/**
 * Flag variant `idx` of an open session. Flagging the same design of the same session again replaces the flag.
 * { session, idx, reasons: [keys of REASONS], note, auto } -> the public flag.
 */
export function addFlag(rootIn, { session, idx, reasons = [], note = '', auto = null } = {}) {
  const prof = detectProject(rootIn);
  const root = prof.root;
  const s = loadSession(root, session);
  const v = s.variants.find((x) => x.idx === Number(idx));
  if (!v) throw new TryonError('NO_VARIANT', `session ${session} has no variant ${idx} (the original cannot be flagged)`);
  const rs = [...new Set([].concat(reasons || []).map(String))];
  const bad = rs.filter((r) => !REASONS[r]);
  if (bad.length) throw new TryonError('BAD_REASON', `unknown reason(s): ${bad.join(', ')}`, { allowed: Object.keys(REASONS) });
  const text = clip(String(note || '').trim(), 2000);
  if (!rs.length && !text) throw new TryonError('NO_REASON', 'say what is wrong: pick a reason or write a note');
  let design = null;
  try {
    const code = fs.readFileSync(path.join(root, v.entry), 'utf8');
    design = { entry: v.entry, slots: designSlots(code), code: clip(code, 12000) };
  } catch { /* the staging folder is gone (kept or discarded since) */ }
  const own = ownerElement(root, s);
  const flag = {
    id: 'F' + crypto.createHash('sha1').update(s.id + '|' + v.id).digest('hex').slice(0, 8),
    createdAt: new Date().toISOString(),
    reasons: rs.sort((a, b) => Object.keys(REASONS).indexOf(a) - Object.keys(REASONS).indexOf(b)),
    note: text,
    where: { file: s.file, line: s.line, col: s.col, slot: s.slot, kind: s.kind, session: s.id, idx: v.idx },
    variant: { id: v.id, title: v.t, registry: v.r, name: v.n, licence: v.lic, source: v.sourceUrl || null, deps: v.deps || [], generated: !!v.generated,
      fit: v.fit ? { carried: v.fit.carried, of: v.fit.of, dropped: (v.fit.dropped || []).map((d) => ({ role: d.role, text: clip(d.text, 200) })),
        demo: strList(v.fit.demo, 12), hidden: strList(v.fit.hidden, 12, 240), demoVisual: v.fit.demoVisual || 0 } : null,
      removedChrome: strList(v.removedChrome, 12) },
    usage: clip(v.usage, 6000),
    owner: own,
    design,
    auto: cleanAuto(auto),
    env: { deckhand: skillVersion(), catalog: catalogBuilt(), framework: prof.framework, base: prof.base, tailwind: prof.tailwind },
  };
  const doc = readFlags(root);
  doc.flags = doc.flags.filter((f) => f.id !== flag.id).concat([flag]);
  writeFlags(root, doc);
  return { ...publicFlag(flag), total: doc.flags.length };
}

export function removeFlag(rootIn, id) {
  const root = detectProject(rootIn).root;
  const doc = readFlags(root);
  const n = doc.flags.length;
  doc.flags = doc.flags.filter((f) => f.id !== id);
  if (doc.flags.length === n) throw new TryonError('NO_FLAG', 'no flag ' + id);
  writeFlags(root, doc);
  return { removed: id, total: doc.flags.length };
}

export function clearFlags(rootIn) {
  const root = detectProject(rootIn).root;
  const n = readFlags(root).flags.length;
  writeFlags(root, { version: 1, flags: [] });
  return { cleared: n, total: 0 };
}

/** A code fence longer than any backtick run inside the text (a design's template literals never close it). */
function fence(text, lang = '') {
  const t = String(text || '');
  const run = Math.max(2, ...[...t.matchAll(/`+/g)].map((m) => m[0].length));
  const f = '`'.repeat(run + 1);
  return `${f}${lang}\n${t.replace(/\s+$/, '')}\n${f}`;
}
const cell = (s) => String(s == null ? '' : s).replace(/\|/g, '\\|').replace(/\s+/g, ' ').trim() || '—';
const q = (s) => `“${String(s).replace(/\s+/g, ' ').trim()}”`;

/**
 * The report: the flags (all, or `ids`) as one Markdown file, sorted by section, registry and design, with the
 * patterns across them first. Written to .deckhand/tryon/reports/tryon-flags-<sha10>.md; { path, flags, markdown }.
 */
export function buildReport(rootIn, ids = null) {
  const root = detectProject(rootIn).root;
  let flags = readFlags(root).flags;
  if (ids && ids.length) flags = flags.filter((f) => ids.includes(f.id));
  if (!flags.length) throw new TryonError('NO_FLAGS', ids && ids.length ? 'none of those flags exist' : 'nothing is flagged yet: flag a variant from the try-on bar (⚑ Flag)');
  flags = flags.slice().sort((a, b) => a.where.slot.localeCompare(b.where.slot) || a.variant.registry.localeCompare(b.variant.registry)
    || a.variant.id.localeCompare(b.variant.id) || a.id.localeCompare(b.id));
  const label = new Map(flags.map((f, i) => [f.id, 'F' + (i + 1)]));
  const env = flags[0].env || {};
  const L = [];
  L.push('# Try-on flag report', '');
  L.push(`Deckhand ${env.deckhand || '?'} · catalog ${env.catalog || '?'} · ${flags.length} flagged variant(s) · ${env.framework || '?'} · primitives ${env.base || '?'} · Tailwind ${env.tailwind ?? '?'}`, '');
  L.push('> **For the AI or person fixing this.** Each flag is a real design that did not work on a real site. Fix the',
    '> engine (`skills/deckhand/tryon/lib`: `transplant.mjs` maps content, `engine.mjs` stages and gates,',
    '> `materialize.mjs` fetches and themes), never one design by its id: the goal is that every design with the same',
    '> shape works. Start with the patterns below. For each flag, run its Reproduce command in a copy of the site, add an',
    '> offline test in `skills/deckhand/tryon/test` that fails first, then make it pass.',
    '> This file contains the site owner\'s own text: do not publish it.', '');
  L.push('## Summary', '', '| # | section | design | registry | problems | content carried |', '|---|---|---|---|---|---|');
  for (const f of flags) {
    L.push(`| ${label.get(f.id)} | ${cell(f.where.slot)} | ${cell(f.variant.title)} | ${cell(f.variant.registry)} | ${cell(f.reasons.join(', ') || 'note only')} | ${f.variant.fit ? `${f.variant.fit.carried}/${f.variant.fit.of}` : '—'} |`);
  }
  L.push('');
  const group = (keyOf) => {
    const m = new Map();
    for (const f of flags) for (const k of [].concat(keyOf(f))) { if (!m.has(k)) m.set(k, []); m.get(k).push(label.get(f.id)); }
    return [...m].sort((a, b) => b[1].length - a[1].length || String(a[0]).localeCompare(String(b[0])));
  };
  L.push('## Patterns', '', '### By problem');
  for (const [k, ls] of group((f) => (f.reasons.length ? f.reasons : ['other']))) L.push(`- **${REASONS[k] || k}** (${ls.length}): ${ls.join(', ')}`);
  L.push('', '### By section');
  for (const [k, ls] of group((f) => f.where.slot)) L.push(`- **${k}** (${ls.length}): ${ls.join(', ')}`);
  L.push('', '### By registry');
  for (const [k, ls] of group((f) => f.variant.registry)) L.push(`- **${k}** (${ls.length}): ${ls.join(', ')}`);
  const lost = group((f) => (f.variant.fit ? f.variant.fit.dropped.map((d) => d.role) : []));
  if (lost.length) {
    L.push('', '### Content the engine dropped, by role');
    for (const [k, ls] of lost) L.push(`- **${k}** (${ls.length}): ${[...new Set(ls)].join(', ')}`);
  }
  L.push('');
  for (const f of flags) {
    const v = f.variant;
    L.push(`## ${label.get(f.id)} — ${f.where.slot} · ${v.title}`, '');
    L.push(`- Problems: ${f.reasons.length ? f.reasons.map((r) => REASONS[r] || r).join('; ') : 'see the note'}`);
    if (f.note) L.push(`- The owner says: ${q(f.note)}`);
    L.push(`- Design: \`${v.id}\` · ${v.licence || '?'}${v.source ? ` · ${v.source}` : ''}${v.generated ? ' · AI-generated draft' : ''}`);
    if (v.deps && v.deps.length) L.push(`- Packages: ${v.deps.join(', ')}`);
    L.push(`- Element: \`${f.where.file}:${f.where.line}:${f.where.col}\` (${f.where.kind})`);
    if (v.fit) {
      L.push(`- Content carried: ${v.fit.carried}/${v.fit.of}`);
      for (const d of v.fit.dropped) L.push(`  - dropped ${d.role}: ${q(d.text)}`);
      if (v.fit.demo.length) L.push(`  - the design's own words still shown: ${v.fit.demo.map(q).join(', ')}`);
      for (const h of v.fit.hidden) L.push(`  - hidden: ${h}`);
    }
    if (v.removedChrome && v.removedChrome.length) L.push(`- Removed from the design (page chrome): ${v.removedChrome.join(', ')}`);
    const a = f.auto;
    if (a) {
      const seen = [];
      if (a.missing.length) seen.push(`words of the owner not on the page: ${a.missing.map(q).join(', ')}`);
      if (a.foreign.length) seen.push(`demo words on the page: ${a.foreign.map(q).join(', ')}`);
      if (a.overflow) seen.push(`${a.overflow} element(s) wider than the screen`);
      if (a.brokenImages.length) seen.push(`broken images: ${a.brokenImages.join(', ')}`);
      if (a.errors.length) seen.push(`console errors: ${a.errors.map(q).join(' ')}`);
      L.push(`- The page (auto-check${a.viewport ? `, ${a.viewport.w}×${a.viewport.h}` : ''}):${seen.length ? '' : ' nothing measurable'}`);
      for (const x of seen) L.push(`  - ${x}`);
    }
    L.push('');
    if (f.owner && f.owner.units.length) {
      L.push('### The owner\'s content (what should be carried)', '', '| role | text |', '|---|---|');
      for (const u of f.owner.units) L.push(`| ${cell(u.role)} | ${cell(u.text)} |`);
      L.push('');
    }
    if (f.owner && f.owner.jsx) L.push('### The owner\'s element, before the try', '', fence(f.owner.jsx, 'tsx'), '');
    if (f.usage) L.push('### What the engine passed to the design', '', fence(f.usage, 'tsx'), '');
    if (f.design) {
      if (f.design.slots.length) {
        L.push('### The design\'s content slots', '', '| slot | the design\'s own words there |', '|---|---|');
        for (const x of f.design.slots) L.push(`| \`${x.slot}\` | ${cell(x.demo)} |`);
        L.push('');
      }
      L.push(`### The design as staged (\`${f.design.entry}\`)`, '', fence(f.design.code, 'tsx'), '');
    }
    L.push('### Reproduce', '', v.generated
      ? `An AI draft: its files are in \`.deckhand/tryon/drafts/${v.id.replace(/^.*-draft-/, '')}/\` on the owner's machine; \`draft-check --id ${v.id.replace(/^.*-draft-/, '')}\` re-runs its gates.`
      : fence(`node skills/deckhand/tryon/cli.mjs try --project <a copy of the site> --file ${f.where.file} --line ${f.where.line} --col ${f.where.col} --slot ${f.where.slot} --only ${v.id} --no-verify`, 'bash'), '');
  }
  const markdown = L.join('\n').replace(/\n{3,}/g, '\n\n').replace(/\s*$/, '\n');
  const name = 'tryon-flags-' + crypto.createHash('sha256').update(markdown).digest('hex').slice(0, 10) + '.md';
  const dir = path.join(stateDir(root), 'reports');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, name), markdown);
  return { path: path.posix.join('.deckhand/tryon/reports', name), flags: flags.length, markdown };
}
