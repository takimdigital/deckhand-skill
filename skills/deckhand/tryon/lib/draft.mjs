/**
 * draft.mjs — the AI fallback for try-on.
 *
 * When no licensed design fits an element (or the owner asks for one), the project's own AI agent
 * writes ONE variant from a brief. Scripts then prove it before the owner sees it:
 *   - every word, link, image and bullet of the owner's element is on it (nothing dropped);
 *   - colours are the site's tokens (no hex / rgb / arbitrary colour values);
 *   - imports are the project's own primitives or installed packages (nothing to install);
 *   - images are the owner's or the neutral placeholder; links go only where the owner's went;
 *   - no data fetching, no env access.
 * Words the owner never wrote are listed as AI-written, never presented as the owner's facts. The
 * variant is labelled AI-generated in the bar, the session, the file header and the keep result.
 * The agent is called once per request — never per click (the v1 polling loop stays dead).
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import * as engine from './engine.mjs';
import { detectProject, specFor, depInstalled } from './project.mjs';
import { extractUnits } from './transplant.mjs';
import { loadCatalog, SKILL_DIR } from './catalog.mjs';
import { importsOf, pkgName } from './registry.mjs';
import { kindOf } from './slots.mjs';

const require = createRequire(import.meta.url);
const { parse, walk, jsxName } = require('./ast.cjs');
const { TryonError } = engine;

const now = () => new Date().toISOString();
const draftsDir = (root) => path.join(engine.stateDir(root), 'drafts');
const docPath = (root, id) => path.join(draftsDir(root), id + '.json');
export const filesDir = (root, id) => path.join(draftsDir(root), id);
const rel = (root, p) => path.relative(root, p).split(path.sep).join('/');
const CLI = path.join(SKILL_DIR, 'tryon', 'cli.mjs');
const TOKEN_CLASSES = ['bg-background', 'text-foreground', 'bg-card', 'text-card-foreground', 'bg-primary', 'text-primary-foreground',
  'text-primary', 'bg-secondary', 'text-secondary-foreground', 'bg-muted', 'text-muted-foreground', 'bg-accent', 'text-accent-foreground',
  'border-border', 'border-input', 'ring-ring', 'bg-destructive'];
const TOOLING = /^(@types\/|typescript$|eslint|prettier|tailwindcss$|@tailwindcss\/|postcss|autoprefixer|tw-animate-css$|vite$|@vitejs\/)/;

export function loadDraft(root, id) {
  if (!/^[A-Za-z0-9_-]{1,40}$/.test(String(id))) throw new TryonError('BAD_ID', 'bad draft id');
  const p = docPath(root, id);
  if (!fs.existsSync(p)) throw new TryonError('NO_DRAFT', 'no AI draft request ' + id);
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}
function saveDraft(root, d) {
  fs.mkdirSync(draftsDir(root), { recursive: true });
  fs.writeFileSync(docPath(root, d.id), JSON.stringify(d, null, 1));
}
export function listDrafts(rootIn, { state } = {}) {
  const root = path.resolve(rootIn);
  const dir = draftsDir(root);
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((f) => f.endsWith('.json')).map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')))
    .filter((d) => !state || [].concat(state).includes(d.state)).sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}
/** What the overlay/CLI shows about a request (the brief itself is for the agent). */
export function publicDraft(d) {
  return { id: d.id, state: d.state, slot: d.request.slot, file: d.request.file, note: d.request.note, createdAt: d.createdAt,
    write_to: d.brief.write_to, then: d.brief.then, problems: d.problems || [], session: d.session || null, ai_copy: d.aiCopy || [] };
}

/**
 * The owner (overlay) or the agent (CLI) asks for an AI variant of one element.
 * { file, line, col, slot, note? } — or { session } to draft beside the variants of an open session.
 */
export function requestDraft(rootIn, { file, line, col, slot, note, session, hint } = {}) {
  const prof = detectProject(rootIn);
  const root = prof.root;
  let relFile, code;
  if (session) {
    const s = engine.loadSession(root, session);
    if (s.state !== 'open') throw new TryonError('SESSION_CLOSED', `session ${session} is ${s.state}`);
    relFile = s.file; line = s.line; col = s.col; slot = slot || s.slot;
    code = fs.readFileSync(path.join(root, s.backup), 'utf8');       // the element as it was before the try
  } else {
    relFile = String(file || '').replace(/\\/g, '/');
    const abs = path.resolve(root, relFile);
    if (!abs.startsWith(root + path.sep)) throw new TryonError('OUTSIDE_PROJECT', relFile + ' is outside the project');
    if (/(^|\/)(node_modules|\.next|dist|build)\//.test(relFile)) throw new TryonError('GENERATED_FILE', relFile + ' is generated/vendored');
    if (/(^|\/)dh-tryon\//.test(relFile)) throw new TryonError('INSIDE_VARIANT', 'that element belongs to a variant being tried — keep or discard it first');
    if (!fs.existsSync(abs)) throw new TryonError('NO_FILE', relFile);
    code = fs.readFileSync(abs, 'utf8');
  }
  slot = String(slot || '').trim();
  if (!slot) throw new TryonError('NO_SLOT', 'say what this element is (hero, pricing, button…)');
  const ast = parse(relFile, code);
  // the page may be older than the file: the element the owner clicked, found again by what it is (not in a session:
  // there the backup IS the file the stamps came from)
  const picked = engine.pickElement(ast, code, line, col, session ? null : hint);
  if (!picked) throw new TryonError('ELEMENT_NOT_FOUND', `no JSX element starts at ${relFile}:${line}:${col} — the page is older than the file: reload it and pick again`, { reload: true });
  const el = picked.el;
  line = picked.line; col = picked.col;
  const orig = extractUnits(code, el, ast);
  const id = 'd' + Date.now().toString(36).slice(-6) + crypto.randomBytes(2).toString('hex');
  const d = {
    id, state: 'pending', createdAt: now(),
    request: { file: relFile, line: Number(line), col: Number(col), slot, kind: kindOf(slot), session: session || null, note: note ? String(note).slice(0, 600) : null },
    brief: brief(prof, { relFile, code, el, orig, slot, note, id }),
  };
  saveDraft(root, d);
  fs.mkdirSync(filesDir(root, id), { recursive: true });
  return { ...publicDraft(d), brief_file: rel(root, docPath(root, id)),
    tell_agent: `Deckhand try-on: the owner asked for an AI draft (${slot}). Read ${rel(root, docPath(root, id))} → "brief", write the component into ${d.brief.write_to}, then run: ${d.brief.then}` };
}

function brief(prof, { relFile, code, el, orig, slot, note, id }) {
  const dynamic = [];
  const lit = (src) => { try { const v = JSON.parse(src); return typeof v === 'string' ? v : null; } catch { return null; } };
  const unit = (u) => {
    if (u.dynamic) {
      const key = 'dyn' + (dynamic.length + 1);
      dynamic.push({ key, src: u.src });
      return { role: u.role, expression: u.src, render: `{content.${key}}` };
    }
    const o = { role: u.role, text: u.text };
    if (/</.test(u.src || '') && u.src.replace(/\s+/g, ' ').trim() !== u.text) o.markup = u.src.replace(/\s+/g, ' ').trim();
    if (u.role === 'action') { o.href = lit(u.href) ?? u.href ?? null; if (u.sub) o.kind = u.sub; }
    return o;
  };
  const flat = orig.units.filter((u) => u.list === null || u.list === undefined).map(unit);
  const lists = orig.lists.map((l) => l.items.map((it) => ({ units: it.units.map(unit), bullets: it.bullets || [], images: (it.images || []).map((i) => ({ src: lit(i.src) ?? i.src, alt: lit(i.alt) ?? i.alt })) })));
  const images = orig.images.map((i) => ({ src: lit(i.src) ?? i.src, alt: lit(i.alt) ?? i.alt }));
  const kind = kindOf(slot);
  const pkgs = Object.keys(prof.deps).filter((d) => !TOOLING.test(d) && depInstalled(prof, d)).sort();
  const writeTo = rel(prof.root, filesDir(prof.root, id));
  const ui = Object.fromEntries(Object.keys(prof.ui).sort().map((n) => [n, specFor(prof, prof.ui[n])]));
  const src = code.slice(el.start, el.end);
  return {
    task: `Write ONE ${slot} ${kind === 'block' ? 'section' : 'component'} for this site that replaces the element below. It will be shown to the owner labelled "AI-generated", beside (or instead of) licensed designs.`,
    owner_note: note ? String(note).slice(0, 600) : null,
    write_to: writeTo,
    entry: 'draft.tsx',
    then: `node "${CLI}" draft-done --project "${prof.root}" --id ${id}`,
    content: { units: flat, lists, images, dynamic_lists: orig.dynamicLists || 0 },
    original: { file: relFile, jsx: src.length > 4000 ? src.slice(0, 4000) + '\n/* …truncated */' : src },
    project: {
      framework: prof.framework, next: prof.nextMajor, rsc: prof.rsc, lang: prof.lang, tailwind: prof.tailwind,
      ui, utils: prof.utilsExists ? specFor(prof, prof.utilsFile) : null, packages: pkgs,
    },
    rules: [
      `Files go in ${writeTo}/ — the entry is draft.tsx with a default export; extra files are imported relatively.`,
      kind === 'block'
        ? (dynamic.length ? 'Signature: export default function X({ content = {} }: { content?: Record<string, any> }) — render each `expression` unit as its `render` value.' : 'Signature: export default function X() — no required props.')
        : 'Signature: a component that renders {children} and forwards ...props to its root element (it replaces a primitive).',
      'Content: use EVERY unit, list item, bullet and image above, verbatim (keep `markup` spans), in a sensible order. Links: exactly the given hrefs, no others (no "#").',
      'Invent no facts: no numbers, prices, names, reviews, logos, claims or dates the owner did not give. Short UI words are allowed and will be shown to the owner as AI-written.',
      `Colours: semantic token classes only (${TOKEN_CLASSES.slice(0, 11).join(', ')}…, with /opacity allowed) — no hex, rgb(), hsl(), oklch() and no bg-[#…] arbitrary colours.`,
      `Imports: react, next/link, next/image, ${Object.values(ui).concat(prof.utilsExists ? [specFor(prof, prof.utilsFile)] : []).join(', ') || 'no project primitives'}, and installed packages only (${pkgs.filter((p) => !/^(react|react-dom|next)$/.test(p)).join(', ') || 'none'}). Nothing new to install.`,
      `Images: only the owner's src values above, else "${engine.PLACEHOLDER}". next/image needs width/height or fill.`,
      prof.rsc ? 'Next app router: add "use client" at the top only if you use hooks, event handlers or motion.' : 'Client component.',
      'Mobile-first responsive, semantic HTML (one heading level per rank, alt text, labelled controls), no data fetching, no process.env, no new routes.',
    ],
  };
}

/* ------------------------------------------------------------------ gates */

function specToFile(prof, spec) {
  if (!prof.alias || !spec.startsWith(prof.alias)) return null;
  const base = path.join(prof.root, prof.codeRoot === '.' ? '' : prof.codeRoot, spec.slice(prof.alias.length));
  for (const e of ['.tsx', '.ts', '.jsx', '.js', '/index.tsx', '/index.ts', '/index.js']) if (fs.existsSync(base + e)) return base + e;
  return null;
}

/** Deterministic checks of what the agent wrote. { ok, problems[], ai_copy[], entry, fit } — writes nothing. */
export function checkDraft(rootIn, id) {
  const prof = detectProject(rootIn);
  const root = prof.root;
  const d = loadDraft(root, id);
  const dir = filesDir(root, id);
  const problems = [];
  const P = (code, detail) => problems.push({ code, detail });
  const files = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => !f.startsWith('.')) : [];
  const codeFiles = files.filter((f) => /\.(tsx|jsx|ts|js)$/.test(f));
  if (!codeFiles.length) { P('DRAFT_EMPTY', `write the component into ${d.brief.write_to}/draft.tsx`); return { ok: false, problems, ai_copy: [], entry: null }; }
  for (const f of files) if (!/\.(tsx|jsx|ts|js)$/.test(f)) P('DRAFT_FILE', `${f}: only .tsx/.ts/.jsx/.js files (style with Tailwind token classes, not CSS files)`);
  const entry = codeFiles.find((f) => /^draft\.(tsx|jsx)$/.test(f)) || null;
  if (!entry) P('DRAFT_ENTRY', 'the entry must be draft.tsx (or draft.jsx) with a default export');
  const imgSrcs = new Set(d.brief.content.images.map((i) => i.src).concat(d.brief.content.lists.flatMap((l) => l.flatMap((it) => it.images.map((i) => i.src))), [engine.PLACEHOLDER]));
  const hrefs = new Set(d.brief.content.units.concat(d.brief.content.lists.flat().flatMap((it) => it.units)).filter((u) => u.href).map((u) => u.href));
  for (const f of codeFiles) {
    const code = fs.readFileSync(path.join(dir, f), 'utf8');
    let ast;
    try { ast = parse(f, code); } catch (e) { P('DRAFT_PARSE', `${f}: ${e.message.split('\n')[0]}`); continue; }
    if (f === entry && !engine.entryExport(f, code)) P('DRAFT_EXPORT', `${f}: export the component (default export)`);
    for (const imp of importsOf(f, code)) {
      const s = imp.spec;
      if (s.startsWith('.')) {
        const t = path.join(dir, s);
        if (!['', '.tsx', '.ts', '.jsx', '.js'].some((e) => fs.existsSync(t + e) && fs.statSync(t + e).isFile())) P('DRAFT_IMPORT', `${f}: ${s} is not a file in the draft folder`);
      } else if (s.startsWith(prof.alias) || s.startsWith('~/')) {
        const ok = /(?:^|\/)ui\/[a-z0-9-]+$/.test(s) ? !!specToFile(prof, s) : (/(?:^|\/)lib\/utils$/.test(s) && prof.utilsExists);
        if (!ok) P('DRAFT_IMPORT', `${f}: ${s} — only the project's ui primitives and utils may be imported (${Object.keys(prof.ui).join(', ') || 'none'})`);
      } else {
        const name = pkgName(s);
        if (!['react', 'react-dom', 'next'].includes(name) && !depInstalled(prof, name)) P('DRAFT_IMPORT', `${f}: ${name} is not installed — use installed packages only`);
      }
    }
    if (/\bfetch\s*\(|process\.env|\bXMLHttpRequest\b|\baxios\b/.test(code)) P('DRAFT_SIDE_EFFECT', `${f}: no data fetching or environment access in a design variant`);
    walk(ast, (n) => {
      if (n.type !== 'JSXAttribute' || !n.name || n.name.type !== 'JSXIdentifier') return true;
      const name = n.name.name;
      const v = n.value;
      const raw = v ? code.slice(v.start, v.end) : '';
      if ((name === 'className' || name === 'style' || name === 'fill' || name === 'stroke' || name === 'color')
        && /(#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(|\[(#|rgb|hsl|oklch))/.test(raw)) {
        P('DRAFT_RAW_COLOR', `${f}:${code.slice(0, n.start).split('\n').length} ${name} uses a raw colour — use the site's token classes`);
      }
      const str = v && v.type === 'StringLiteral' ? v.value : (v && v.type === 'JSXExpressionContainer' && v.expression.type === 'StringLiteral' ? v.expression.value : null);
      if (name === 'src' && str != null && !imgSrcs.has(str)) P('DRAFT_IMAGE', `${f}: src "${str}" — use the owner's images or ${engine.PLACEHOLDER}`);
      if (name === 'href' && str != null && !hrefs.has(str)) P('DRAFT_LINK', `${f}: href "${str}" — links go only where the owner's did (${[...hrefs].join(', ') || 'none given'})`);
      return true;
    });
  }
  let fit = null;
  // content is measured whenever the files can be read, so one rejection lists every problem (a bad link AND the
  // dropped words), not one round per kind of problem
  if (!problems.some((p) => ['DRAFT_ENTRY', 'DRAFT_PARSE', 'DRAFT_EXPORT'].includes(p.code))) {
    // content: measured on the files as written (same measure the variant bar shows)
    const orig = origFromBrief(d);
    fit = engine.literalFit(root, rel(root, dir), orig, dynamicOf(d));
    for (const x of fit.dropped) P('DRAFT_DROPPED_CONTENT', `missing ${x.role}: "${x.text.slice(0, 120)}"`);
  }
  return { ok: !problems.length, problems, ai_copy: fit ? fit.invented : [], entry, fit: fit ? { carried: fit.carried.length, of: fit.of } : null };
}

const dynamicOf = (d) => d.brief.content.units.concat(d.brief.content.lists.flat().flatMap((it) => it.units))
  .filter((u) => u.expression).map((u) => ({ key: /content\.(\w+)/.exec(u.render)[1], src: u.expression }));

/** The owner's content as extractUnits() shapes it, rebuilt from the brief (what the gate and fit measure). */
function origFromBrief(d) {
  const c = d.brief.content;
  const u2 = (u, list = null) => ({ role: u.role, text: u.text || '', src: u.expression || u.markup || u.text || '', dynamic: !!u.expression,
    href: u.href ? JSON.stringify(u.href) : null, list });
  const units = c.units.map((u) => u2(u));
  const lists = c.lists.map((items, li) => ({ items: items.map((it) => ({ units: it.units.map((u) => u2(u, li)), bullets: it.bullets || [], images: [] })) }));
  lists.forEach((l) => l.items.forEach((it) => units.push(...it.units)));
  return { units, images: c.images.map((i) => ({ src: JSON.stringify(i.src), alt: JSON.stringify(i.alt || '') })), inputs: [], lists, dynamicLists: 0 };
}

/**
 * The agent is done writing: gate it, then show it. Rejected -> problems listed, state 'rejected' (fix and
 * run again). Accepted -> a try-on session whose AI variant is labelled; with `session`, the registry
 * variants the owner was comparing come back beside it.
 */
export async function completeDraft(rootIn, id, { install = false, onProgress } = {}) {
  const prof = detectProject(rootIn);
  const root = prof.root;
  const d = loadDraft(root, id);
  if (d.state === 'done') throw new TryonError('DRAFT_DONE', `draft ${id} is already on the page (session ${d.session})`);
  const g = checkDraft(root, id);
  d.checkedAt = now();
  if (!g.ok) {
    d.state = 'rejected';
    d.problems = g.problems;
    saveDraft(root, d);
    throw new TryonError('DRAFT_REJECTED', `the AI draft failed ${g.problems.length} check(s) — fix them in ${d.brief.write_to} and run draft-done again`, { problems: g.problems });
  }
  const r = d.request;
  const item = {
    id: `ai/${r.slot}-draft-${id}`, r: 'ai', n: `${r.slot}-draft-${id}`, t: `AI draft · ${r.slot}`, lic: 'AI-generated',
    slot: r.slot, kind: r.kind, base: 'any', ai: true, draft: id, draftDir: filesDir(root, id), entry: g.entry, deps: [], dynamic: dynamicOf(d),
  };
  let at = { file: r.file, line: r.line, col: r.col };
  let candidates = [item];
  // the owner was comparing registry variants (asked from the bar, or opened some while the agent wrote):
  // they return beside the AI one — the file is restored first, never wrapped twice
  let s = null;
  if (r.session) { try { s = engine.loadSession(root, r.session); } catch { /* gone */ } }
  if (!s || s.state !== 'open') s = engine.listSessions(root).find((o) => o.state === 'open' && o.file === r.file && o.line === r.line && o.col === r.col) || null;
  if (s && s.state === 'open') {
    const cat = loadCatalog();
    const prev = s.variants.filter((v) => !v.generated).map((v) => cat.find((c) => c.id === v.id)).filter(Boolean);
    engine.discard(root, s.id, { reason: 'ai draft ' + id });
    at = { file: s.file, line: s.line, col: s.col };
    candidates = [item, ...prev];
  }
  const sess = await engine.open(root, { ...at, slot: r.slot, candidates, count: candidates.length, install, onProgress });
  const v = sess.variants.find((x) => x.generated);
  d.state = 'done';
  d.session = sess.id;
  d.problems = [];
  d.aiCopy = g.ai_copy;
  d.doneAt = now();
  saveDraft(root, d);
  return { ...sess, draft: id, ai_variant: v ? v.idx : null, ai_copy: g.ai_copy };
}
