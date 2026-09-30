/**
 * engine.mjs — one try-on session, end to end, with no LLM in the loop.
 *
 *   open()    click target (file:line:col) -> N ranked, fetched, themed, content-transplanted
 *             variants written ONCE into the source inside a wrapper; HMR renders them; cycling
 *             is client-side (display toggles) so browsing variants costs zero writes.
 *   show()    persist which variant is visible (headless agents / reloads).
 *   keep()    the wrapper collapses to the chosen variant; literal copy is baked into the
 *             component; its folder graduates to components/sections|ui-kit; losers are deleted.
 *   discard() byte-exact restore (or a surgical unwrap if the file changed since).
 * State: <project>/.deckhand/tryon/{sessions/*.json,backups/} — the journal is the truth.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import http from 'node:http';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { detectProject, specFor } from './project.mjs';
import { loadCatalog, rank, SKILL_DIR } from './catalog.mjs';
import { fetchBundle, writeBundle, pascal, slugOf, entryExport } from './materialize.mjs';
import { extractUnits, parameterize, bind, contentProp, shapeOf, contentCount, ownerLogos, defaultPropsOf } from './transplant.mjs';
import { itemCss, tokenLayer } from './theme.mjs';
import { kindOf } from './slots.mjs';
import { siteLinks, fillLinks, linkTexts, FORM_SLOTS } from './sitelinks.mjs';

const require = createRequire(import.meta.url);
const { parse, walk, jsxName, findElementAt, attr, lineCol, offsetOf } = require('./ast.cjs');

export class TryonError extends Error {
  constructor(code, message, extra = {}) { super(message); this.code = code; Object.assign(this, extra); }
}

const PLACEHOLDER_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000"><rect width="1600" height="1000" fill="#e7e5e4"/><path d="M700 600l120-150 90 110 60-70 130 160z" fill="#a8a29e"/><circle cx="930" cy="400" r="40" fill="#a8a29e"/><text x="800" y="720" text-anchor="middle" font-family="system-ui,sans-serif" font-size="36" fill="#78716c">your image</text></svg>\n';
export const PLACEHOLDER = '/deckhand-placeholder.svg';

/** A neutral image placeholder in public/ (a registry's demo screenshot is never shown as the owner's). */
export function ensurePlaceholder(prof) {
  const pub = path.join(prof.root, 'public');
  // Next and Vite serve public/ at the site root by default — a fresh app may simply not have one yet
  if (!fs.existsSync(pub)) {
    if (!['next', 'vite'].includes(prof.framework)) return false;
    fs.mkdirSync(pub, { recursive: true });
  }
  const p = path.join(pub, 'deckhand-placeholder.svg');
  if (!fs.existsSync(p)) fs.writeFileSync(p, PLACEHOLDER_SVG);
  return true;
}
const sha = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
const now = () => new Date().toISOString();

export function stateDir(root) { return path.join(root, '.deckhand', 'tryon'); }
function sessionsDir(root) { return path.join(stateDir(root), 'sessions'); }
export function loadSession(root, id) {
  if (!/^[A-Za-z0-9_-]{1,40}$/.test(String(id))) throw new TryonError('BAD_ID', 'bad session id');
  const p = path.join(sessionsDir(root), id + '.json');
  if (!fs.existsSync(p)) throw new TryonError('NO_SESSION', 'no try-on session ' + id);
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}
function saveSession(root, s) {
  fs.mkdirSync(sessionsDir(root), { recursive: true });
  fs.writeFileSync(path.join(sessionsDir(root), s.id + '.json'), JSON.stringify(s, null, 2));
}
export function listSessions(root) {
  const d = sessionsDir(root);
  if (!fs.existsSync(d)) return [];
  return fs.readdirSync(d).filter((f) => f.endsWith('.json')).map((f) => JSON.parse(fs.readFileSync(path.join(d, f), 'utf8')))
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}
function newId(root) {
  const n = listSessions(root).length + 1;
  return 's' + n + crypto.randomBytes(2).toString('hex');
}

function identifiers(code) { return new Set(code.match(/[A-Za-z_$][\w$]*/g) || []); }
function uniqueName(base, taken) {
  let n = base, i = 2;
  while (taken.has(n)) n = base + i++;
  taken.add(n);
  return n;
}

function importInsertPos(ast, code) {
  let last = null;
  for (const st of ast.program.body) if (st.type === 'ImportDeclaration') last = st;
  if (last) return code.indexOf('\n', last.end) === -1 ? code.length : code.indexOf('\n', last.end) + 1;
  // after directives ("use client")
  let pos = 0;
  for (const d of ast.program.directives || []) pos = code.indexOf('\n', d.end) + 1;
  return pos;
}

function indentAt(code, offset) {
  const ls = code.lastIndexOf('\n', offset - 1) + 1;
  return (/^[ \t]*/.exec(code.slice(ls, offset)) || [''])[0];
}

/** Find the wrapper JSXElement for a session in the current text. */
function findWrapper(ast, id) {
  let hit = null;
  walk(ast, (n) => {
    if (hit) return false;
    if (n.type === 'JSXElement') {
      const a = attr(n, 'data-dh-session');
      if (a && a.value && a.value.type === 'StringLiteral' && a.value.value === id) { hit = n; return false; }
    }
    return true;
  });
  return hit;
}
function variantChildren(wrapper) {
  return (wrapper.children || []).filter((c) => c.type === 'JSXElement' && attr(c, 'data-dh-variant'));
}
function innerSrc(code, el) {
  const kids = el.children || [];
  const s = kids.length ? code.slice(kids[0].start, kids[kids.length - 1].end) : '';
  return s.trim();
}

/** A primitive swap keeps the usage's props/children; `asChild` + single child is unwrapped. */
function primitiveUsage(code, el, local, candCode, extra = []) {
  const op = el.openingElement;
  const kids = (el.children || []).filter((c) => !(c.type === 'JSXText' && !c.value.trim()));
  const keepAttr = (a) => {
    if (a.type !== 'JSXAttribute') return true;
    const n = a.name.name;
    if (n === 'asChild') return false;
    if ((n === 'variant' || n === 'size') && !new RegExp('\\b' + n + '\\b').test(candCode)) return false;
    return true;
  };
  const attrs = op.attributes.filter(keepAttr).map((a) => code.slice(a.start, a.end)).concat(extra).join(' ');
  const asChild = op.attributes.some((a) => a.type === 'JSXAttribute' && a.name.name === 'asChild');
  if (asChild && kids.length === 1 && kids[0].type === 'JSXElement') {
    const child = kids[0];
    const cop = child.openingElement;
    const cname = jsxName(cop.name);
    const cattrs = cop.attributes.map((a) => code.slice(a.start, a.end)).join(' ');
    const inner = innerSrc(code, child);
    return `<${cname}${cattrs ? ' ' + cattrs : ''}><${local}${attrs ? ' ' + attrs : ''}>${inner}</${local}></${cname}>`;
  }
  const inner = innerSrc(code, el);
  return inner ? `<${local}${attrs ? ' ' + attrs : ''}>${inner}</${local}>` : `<${local}${attrs ? ' ' + attrs : ''} />`;
}

export function install(prof, pkgs, log) {
  if (!pkgs.length) return { ok: true };
  const cmd = { pnpm: ['pnpm', 'add'], yarn: ['yarn', 'add'], bun: ['bun', 'add'], npm: ['npm', 'install', '--no-audit', '--no-fund'] }[prof.pm] || ['npm', 'install'];
  log && log({ phase: 'install', pkgs });
  const r = spawnSync(cmd[0], [...cmd.slice(1), ...pkgs], { cwd: prof.root, encoding: 'utf8', shell: process.platform === 'win32', timeout: 300000 });
  return { ok: r.status === 0, cmd: cmd.concat(pkgs).join(' '), out: ((r.stdout || '') + (r.stderr || '')).split('\n').slice(-8).join('\n') };
}

/**
 * Does a design's component show what is put inside it? `{children}` (or props.children) in its JSX, or its props
 * spread onto an element (`<div {...props}>` carries children). A self-contained demo (a tweet, a flip card) does not.
 */
export function rendersChildren(file, code, exp) {
  let ast;
  try { ast = parse(file, code); } catch { return true; }
  let fn = null;
  const want = exp && exp.kind === 'named' ? exp.name : null;
  const pick = (d) => (d && /Function/.test(d.type) ? d : d && d.type === 'VariableDeclarator' && d.init && /Function/.test(d.init.type) ? d.init : null);
  const byName = new Map();
  walk(ast, (n) => {
    if (n.type === 'FunctionDeclaration' && n.id) byName.set(n.id.name, n);
    if (n.type === 'VariableDeclarator' && n.id.type === 'Identifier' && n.init) {
      let i = n.init;
      if (i.type === 'CallExpression' && i.arguments[0] && /Function/.test(i.arguments[0].type)) i = i.arguments[0];   // forwardRef(…), memo(…)
      if (/Function/.test(i.type)) byName.set(n.id.name, i);
    }
    return true;
  });
  for (const st of ast.program.body) {
    if (want && st.type === 'ExportNamedDeclaration') {
      if (st.declaration && st.declaration.type === 'FunctionDeclaration' && st.declaration.id && st.declaration.id.name === want) fn = st.declaration;
      for (const d of (st.declaration && st.declaration.declarations) || []) if (d.id.name === want) fn = pick(d) || byName.get(want);
      for (const sp of st.specifiers || []) if ((sp.exported.name || sp.exported.value) === want) fn = byName.get(sp.local.name);
    }
    if (!want && st.type === 'ExportDefaultDeclaration') fn = /Function/.test(st.declaration.type) ? st.declaration : st.declaration.type === 'Identifier' ? byName.get(st.declaration.name) : null;
  }
  if (!fn) return true;                                           // cannot tell: treat it as a wrapper (the old behaviour)
  const p0 = fn.params[0];
  const spreadNames = new Set();
  if (p0 && p0.type === 'Identifier') spreadNames.add(p0.name);
  if (p0 && p0.type === 'ObjectPattern') for (const pr of p0.properties) if (pr.type === 'RestElement' && pr.argument.type === 'Identifier') spreadNames.add(pr.argument.name);
  // where the owner's content would land: inside a text element (`<p>{children}</p>`) only words may go — a card's
  // divs and paragraphs there are invalid HTML (hydration errors on every render)
  const PHRASING = /^(p|span|a|button|label|h[1-6]|strong|em|b|i|small|q|cite|dt|summary|legend|option)$/;
  let block = false, inline = false;
  const VOID_TAG = /^(input|img|br|hr|area|base|col|embed|link|meta|source|track|wbr)$/;
  const visit = (n, host) => {
    if (!n || typeof n.type !== 'string' || inline) return;
    if (n.type === 'JSXElement') {
      const nm = jsxName(n.openingElement.name);
      // `<button {...props}>` passes the owner's children on — unless the element writes children of its own
      // (`<Button {...props}><span>Hover me</span></Button>`: JSX children win over props.children)
      if (n.openingElement.attributes.some((a) => a.type === 'JSXSpreadAttribute' && a.argument.type === 'Identifier' && spreadNames.has(a.argument.name))
        && !(n.children || []).some((c) => !(c.type === 'JSXText' && !c.value.trim()))) {
        // a void element (`<input {...props} />`) cannot take children: React throws on render, so it is no wrapper
        if (VOID_TAG.test(nm)) return;
        if (PHRASING.test(nm)) inline = true; else block = true;
      }
      if (/^[a-z]/.test(nm)) host = nm;
    }
    if ((n.type === 'Identifier' && n.name === 'children') || (n.type === 'MemberExpression' && !n.computed && n.property.name === 'children')) {
      if (host && PHRASING.test(host)) inline = true; else block = true;
      return;
    }
    for (const k of Object.keys(n)) {
      if (k === 'loc' || k === 'start' || k === 'end' || k === 'extra' || /Comments$/.test(k)) continue;
      const v = n[k];
      if (Array.isArray(v)) for (const c of v) visit(c, host);
      else if (v && typeof v.type === 'string') visit(v, host);
    }
  };
  visit(fn.body, null);
  // once anywhere inside a text element, only words may go in (`{(subtitle || children) && <p>{children}</p>}`)
  return inline ? 'inline' : block;
}

/** A wrapper design takes the owner's content inside it — words only, when it puts them in a text element. */
function wrapsContent(rc, el) {
  if (rc === true) return true;
  if (rc !== 'inline') return false;
  let blocky = false;
  walk(el, (n) => {
    if (blocky) return false;
    if (n !== el && n.type === 'JSXElement') { const nm = jsxName(n.openingElement.name); if (!/^(span|strong|em|b|i|small|br|svg|path|img|code|kbd|sup|sub|abbr|time|mark|a|Link|NavLink)$/.test(nm) && !/Icon$|^Lucide/.test(nm)) blocky = true; }
    return !blocky;
  });
  return !blocky;
}

/** The owner's brand name: brief first, then package.json. */
export function brandName(root) {
  try { const b = JSON.parse(fs.readFileSync(path.join(root, '.deckhand', 'brief.json'), 'utf8')); if (b.brand?.name || b.name) return b.brand?.name || b.name; } catch { /* none */ }
  try { const n = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).name; return n ? n.replace(/[-_]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : null; } catch { return null; }
}

/** Ensure the semantic token layer exists (idempotent; recorded for `clean`). */
export function ensureTokens(prof, probe = {}) {
  if (!prof.globalsCss || prof.tailwind !== 4) return { changed: false, reason: prof.tailwind === 4 ? 'NO_GLOBALS_CSS' : 'TAILWIND_' + prof.tailwind };
  const p = path.join(prof.root, prof.globalsCss);
  const css = fs.readFileSync(p, 'utf8');
  if (css.includes('deckhand:tokens')) return { changed: false, reason: 'PRESENT' };
  const layer = tokenLayer(css, probe);
  if (!layer) return { changed: false, reason: 'COMPLETE' };
  fs.writeFileSync(p, css + (css.endsWith('\n') ? '' : '\n') + layer);
  return { changed: true, file: prof.globalsCss };
}

function appendCss(prof, block) {
  if (!block || !prof.globalsCss) return false;
  const p = path.join(prof.root, prof.globalsCss);
  const css = fs.readFileSync(p, 'utf8');
  const tag = /dh:css ([^ ]+) \*\//.exec(block)[1];
  if (css.includes(`/* dh:css ${tag} */`)) return false;
  fs.writeFileSync(p, css + (css.endsWith('\n') ? '' : '\n') + '\n' + block);
  return true;
}
function removeCss(prof, tag) {
  if (!prof.globalsCss) return;
  const p = path.join(prof.root, prof.globalsCss);
  const css = fs.readFileSync(p, 'utf8');
  const a = css.indexOf(`/* dh:css ${tag} */`);
  if (a === -1) return;
  const endTag = `/* /dh:css ${tag} */`;
  const b = css.indexOf(endTag, a);
  if (b === -1) return;
  const start = css.slice(a - 1, a) === '\n' ? a - 1 : a;       // the blank separator appendCss added
  fs.writeFileSync(p, css.slice(0, start) + css.slice(b + endTag.length).replace(/^\n/, ''));
}

/** The most variants one session holds: the owner browses the pool with More, a batch at a time, up to this. */
export const MAX_VARIANTS = 30;
/** Skips that say something about the design itself (never offered again in this session); a download that failed
 *  or a design held back for its npm packages may be offered by the next batch. */
const FINAL_SKIPS = new Set(['POOR_FIT', 'UNRESOLVED_IMPORT', 'NO_EXPORT', 'PARAMETERIZE_FAILED', 'BROKEN_IMPORT']);

/** The pool for one element: every licensed candidate for its slot here, and how many are still untried. */
export function poolOf(catalog, { slot, prof, registry = null }, tried = []) {
  const all = rank(catalog, { slot, prof, registry }).items;
  const t = new Set(tried);
  return { total: all.length, left: all.filter((x) => !t.has(x.id)).length };
}

/**
 * Open a session. opts: { file, line, col, slot, count=4 (≤ MAX_VARIANTS), exclude=[], only=[ids], first=[ids],
 *   registry, stripChrome, install=true, probe, onProgress, candidates, tried }
 * `first`: these designs, when staged, keep their order at the front (More re-shows the batch the owner saw).
 */
export async function open(rootIn, opts) {
  const prof = detectProject(rootIn);
  const root = prof.root;
  const log = opts.onProgress || (() => {});
  const rel = String(opts.file).replace(/\\/g, '/');
  const abs = path.resolve(root, rel);
  if (!abs.startsWith(root + path.sep)) throw new TryonError('OUTSIDE_PROJECT', rel + ' is outside the project');
  if (/(^|\/)(node_modules|\.next|dist|build)\//.test(rel)) throw new TryonError('GENERATED_FILE', rel + ' is generated/vendored — pick the element in your source');
  if (/(^|\/)dh-tryon\//.test(rel)) throw new TryonError('INSIDE_VARIANT', 'that element belongs to a variant being tried — keep or discard it first');
  const before = fs.readFileSync(abs);
  const code = before.toString('utf8');
  const ast = parse(rel, code);
  // the element is already in a try: the wrapper and its import moved it, so the coordinates the page still shows
  // (the ones the try was opened at) find nothing, or the wrapper: say that, not "reload the page"
  const pos = offsetOf(code, Number(opts.line), Number(opts.col));
  const busyHere = listSessions(root).find((o) => o.state === 'open' && o.file === rel && ((o.line === Number(opts.line) && o.col === Number(opts.col))
    || (() => { const w = findWrapper(ast, o.id); return w && w.start <= pos && pos < w.end; })()));
  if (busyHere) throw new TryonError('SESSION_OPEN', `that element is already being tried (session ${busyHere.id}): keep or discard it first`, { id: busyHere.id });
  const picked = pickElement(ast, code, opts.line, opts.col, opts.hint);
  if (!picked) throw new TryonError('ELEMENT_NOT_FOUND', `no JSX element starts at ${rel}:${opts.line}:${opts.col} — the page is older than the file: reload it and pick again`, { reload: true });
  const el = picked.el;
  if (picked.relocated) { opts = { ...opts, line: picked.line, col: picked.col }; log({ phase: 'relocated', line: picked.line, col: picked.col }); }
  const slot = String(opts.slot || '').trim();
  if (!slot) throw new TryonError('NO_SLOT', 'say what this element is (hero, pricing, button…)');
  const kind = kindOf(slot);
  const count = Math.max(1, Math.min(MAX_VARIANTS, Number(opts.count || 4)));

  const orig = extractUnits(code, el, ast);
  const origShape = shapeOf(orig);
  const origCount = contentCount(orig);
  const warning = emptyUsage(el, orig);
  const catalog = loadCatalog();
  // opts.candidates: an explicit list (an AI draft, alone or beside the registry variants it joins)
  const exclude = opts.exclude || [];
  // `only`: exactly these designs (a flag report's reproduce command), in rank order
  const only = [].concat(opts.only || []).flatMap((x) => String(x).split(',')).map((x) => x.trim()).filter(Boolean);
  const ranked = opts.candidates ? { items: opts.candidates.filter((c) => !exclude.includes(c.id)), hidden: 0 } : rank(catalog, { slot, prof, exclude, registry: opts.registry || null, includeBroken: only.length > 0 });
  if (only.length) ranked.items = ranked.items.filter((c) => only.includes(c.id) || only.includes(String(c.id).replace(/@[\w-]+$/, '')));
  if (!ranked.items.length) {
    throw new TryonError('NO_CANDIDATES', `no licensed ${slot} candidates for a ${prof.base} project` + (ranked.hidden ? ` (${ranked.hidden} hidden: other primitive base)` : ''),
      { draft: { file: rel, line: Number(opts.line), col: Number(opts.col), slot } });
  }

  if (kind === 'block' || opts.tokens !== false) {
    const t = ensureTokens(prof, opts.probe || {});
    if (t.changed) log({ phase: 'tokens', file: t.file });
  }

  const hasPublic = ensurePlaceholder(prof);
  const id = newId(root);
  const taken = identifiers(code);
  const variants = [];
  const skipped = [];
  const stripChrome = opts.stripChrome ?? (slot !== 'navbar');
  const links = ['footer', 'navbar'].includes(slot) ? siteLinks(root) : null;
  // a variant folder another open session is showing is never re-staged (it would be wiped)
  const busy = new Set(listSessions(root).filter((o) => o.state === 'open').flatMap((o) => o.variants.map((v) => v.slug)));
  // a variant that needs a package installed comes last: a running dev server may not see a new package until it
  // restarts (the owner's page broke on exactly that). Offered only when too few install-free ones exist.
  const held = [];
  const ctx = { root, code, el, orig, origCount, kind, slot, stripChrome, links, hasPublic, taken, sessionId: id, log,
    noFitGate: opts.noFitGate, checkImports: opts.checkImports };
  for (const cand of ranked.items) {
    if (variants.length >= count || variants.length + held.length >= count * 3) break;
    if (skipped.length > count * 3) break;
    if (busy.has(slugOf(cand))) continue;
    const r = await stageCandidate(ctx, cand);
    if (r.skip) skipped.push(r.skip);
    else if (r.held) held.push(r.held);
    else variants.push(r.v);
  }
  for (const v of held) {
    if (variants.length < count) { variants.push(v); continue; }
    skipped.push({ id: v.id, why: 'NEEDS_DEPS', detail: `${v.missingDeps.join(', ')} (designs that need no install were preferred)` });
    fs.rmSync(path.join(root, v.dir), { recursive: true, force: true });
  }
  if (!variants.length) throw new TryonError('NO_VARIANTS', noVariantsWhy(skipped, slot), { skipped, draft: { file: rel, line: Number(opts.line), col: Number(opts.col), slot } });

  // one batched install for everything the batch needs
  const need = [...new Set(variants.flatMap((v) => v.missingDeps))];
  let installed = [];
  if (need.length) {
    if (opts.install === false) {
      for (const v of [...variants]) if (v.missingDeps.length) {
        skipped.push({ id: v.id, why: 'NEEDS_DEPS', detail: v.missingDeps.join(', ') });
        fs.rmSync(path.join(root, v.dir), { recursive: true, force: true });
        variants.splice(variants.indexOf(v), 1);
      }
      if (!variants.length) throw new TryonError('NO_VARIANTS', 'every candidate needs npm packages; re-run with install', { skipped });
    } else {
      const r = install(prof, need, log);
      if (!r.ok) {
        for (const v of variants) fs.rmSync(path.join(root, v.dir), { recursive: true, force: true });
        throw new TryonError('INSTALL_FAILED', r.cmd + '\n' + r.out, { skipped });
      }
      installed = need;
    }
  }
  // nothing is wired that does not resolve: a missing package or export would break the owner's page
  // (a design importing lucide's removed `Github` icon, an uninstallable Radix part) — that variant is dropped.
  // The install-free ones were checked as they were staged; what was just installed is checked now.
  const gate = opts.checkImports === false ? { bad: new Map() } : checkImports(root, variants.filter((v) => v.missingDeps.length));
  for (const [v, why] of gate.bad) {
    skipped.push({ id: v.id, why: 'BROKEN_IMPORT', detail: why });
    fs.rmSync(path.join(root, v.dir), { recursive: true, force: true });
    variants.splice(variants.indexOf(v), 1);
  }
  if (!variants.length) throw new TryonError('NO_VARIANTS', 'every candidate imports something this project cannot load', { skipped, draft: { file: rel, line: Number(opts.line), col: Number(opts.col), slot } });
  // best fit first: most of the owner's content, then the least leftover demo copy (rank breaks ties); the designs
  // the owner already saw (`first`, a More) keep their places in front, so browsing never reshuffles them
  const first = opts.first || [];
  const placeOf = (v) => { const i = first.indexOf(v.id); return i === -1 ? first.length : i; };
  variants.sort((a, b) => placeOf(a) - placeOf(b) || (b.fit.of ? b.fit.carried / b.fit.of : 0) - (a.fit.of ? a.fit.carried / a.fit.of : 0) || a.fit.demoVisual - b.fit.demoVisual);
  variants.forEach((v, i) => { v.idx = i + 1; });
  for (const v of variants) if (v.css) appendCss(prof, v.css);

  // write the wrapper — ONE edit, re-parsed before it touches disk
  const ind = indentAt(code, el.start);
  const keyA = attr(el, 'key');
  const keySrc = keyA ? ' ' + code.slice(keyA.start, keyA.end) : '';
  const origSrc = code.slice(el.start, el.end);
  const lines = [`<div data-dh-session="${id}"${keySrc} style={{ display: "contents" }}>`,
    `${ind}  <div data-dh-variant="0" data-dh-label="Original" style={{ display: "none" }}>`,
    `${ind}    ${origSrc}`,
    `${ind}  </div>`];
  for (const v of variants) {
    lines.push(`${ind}  <div data-dh-variant="${v.idx}" data-dh-label=${JSON.stringify(v.t)} style={{ display: "${v.idx === 1 ? 'contents' : 'none'}" }}>`,
      `${ind}    ${v.usage}`, `${ind}  </div>`);
  }
  lines.push(`${ind}</div>`);
  let next = code.slice(0, el.start) + lines.join('\n') + code.slice(el.end);
  const imports = variants.map((v) => (v.export.kind === 'default'
    ? `import ${v.local} from ${JSON.stringify(v.spec)} // dh-tryon:${id}\n`
    : `import { ${v.export.name} as ${v.local} } from ${JSON.stringify(v.spec)} // dh-tryon:${id}\n`)).join('');
  const at = importInsertPos(parse(rel, next), next);
  next = next.slice(0, at) + imports + next.slice(at);
  parse(rel, next);                                              // throws PARSE_FAILED: nothing written

  const bdir = path.join(stateDir(root), 'backups', id);
  fs.mkdirSync(bdir, { recursive: true });
  fs.writeFileSync(path.join(bdir, path.basename(rel) + '.orig'), before);
  fs.writeFileSync(abs, next);
  const session = {
    id, createdAt: now(), state: 'open', file: rel, line: Number(opts.line), col: Number(opts.col), slot, kind,
    shaBefore: sha(before), shaAfter: sha(Buffer.from(next)), backup: path.relative(root, path.join(bdir, path.basename(rel) + '.orig')).split(path.sep).join('/'),
    shown: 1, origShape, variants, skipped, installed, hidden: ranked.hidden, registry: opts.registry || null,
    ...(warning ? { warning } : {}),
    // every design this element has been offered or refused (a More continues after them, never repeats them)
    tried: [...new Set((opts.tried || []).concat(exclude, variants.map((v) => v.id), skipped.filter((k) => FINAL_SKIPS.has(k.why)).map((k) => k.id)))],
  };
  session.pool = poolOf(catalog, { slot, prof, registry: session.registry }, session.tried);
  saveSession(root, session);
  return publicSession(session);
}

/**
 * Everything stageCandidate needs to know about the owner's element, built the way open() builds it (the registry
 * fit check stages designs against a reference section through this too).
 */
export function stagingContext(prof, { code, ast, el, slot, sessionId, stripChrome, log, noFitGate, checkImports }) {
  const root = prof.root;
  const orig = extractUnits(code, el, ast);
  return {
    root, code, el, orig, origCount: contentCount(orig), kind: kindOf(slot), slot, sessionId, log,
    stripChrome: stripChrome ?? (slot !== 'navbar'), links: ['footer', 'navbar'].includes(slot) ? siteLinks(root) : null,
    hasPublic: ensurePlaceholder(prof), taken: identifiers(code), noFitGate, checkImports,
  };
}

/**
 * Stage ONE candidate for the owner's element: fetched, themed, the owner's content transplanted, fit-gated and
 * import-checked. {v} a variant (idx set by the caller) · {held: v} it needs a package installed · {skip}. open() and
 * the registry fit check both use it, so a design the check passes is exactly one the owner is offered.
 */
export async function stageCandidate(ctx, cand) {
  const { root, code, el, orig, origCount, kind, slot, stripChrome, links, hasPublic, taken, log = () => {} } = ctx;
  const id = ctx.sessionId;
  const opts = { noFitGate: ctx.noFitGate, checkImports: ctx.checkImports };
  const skip = (why, detail, dir) => { if (dir) fs.rmSync(path.join(root, dir), { recursive: true, force: true }); return { skip: { id: cand.id, why, detail: String(detail || '').slice(0, 200) } }; };
  log({ phase: 'fetch', id: cand.id });
  let stage;
  try {
    const bundle = await fetchBundle(detectProject(root), cand);
    stage = writeBundle(detectProject(root), cand, bundle);
  } catch (e) { return skip(e.code || 'FETCH', e.message); }
  if (stage.problems.length || !stage.export) return skip(stage.export ? 'UNRESOLVED_IMPORT' : 'NO_EXPORT', stage.problems.join('; '), stage.relDir);
  let fit = { carried: [], dropped: [], demo: [], hidden: [] };
  let usage;
  const local = uniqueName('Dh' + pascal(cand.n).slice(0, 40), taken);
  const entryAbs = path.join(root, stage.entry);
  const entryCode = fs.readFileSync(entryAbs, 'utf8');
  if (cand.ai) {
    // an AI draft already holds the owner's words (its gate proved it): measured, never transplanted
    const lf = literalFit(root, stage.relDir, orig, cand.dynamic || []);
    fit = { carried: lf.carried, dropped: lf.dropped, demo: lf.invented.map((t) => ({ text: 'AI-written: ' + t })), hidden: [], demoVisual: lf.invented.length };
    const props = (cand.dynamic || []).map((d) => [d.key, `<>${d.src}</>`]);
    usage = kind === 'block' ? `<${local}${contentProp('content', props)} />` : primitiveUsage(code, el, local, entryCode);
    stage.prop = props.length ? 'content' : null;
    stage.ownerTexts = orig.units.map((x) => x.text).concat(orig.lists.flatMap((l) => l.items.flatMap((it) => it.units.map((u) => u.text).concat(it.bullets || []))));
  } else if (kind === 'block' || (origCount > 0 && !wrapsContent(rendersChildren(stage.entry, entryCode, stage.export), el))) {
    // a section — or a "card"/"button" that never shows what is put inside it (a demo tweet, a flip card with its
    // own title): the owner's words go into its props like a section's, or it is not offered
    const logoLocals = logoLocalsFor(stage, entryCode);
    let p;
    try { p = parameterize(stage.entry, entryCode, stage.export, { stripChrome, logoLocals, logoSwap: ownerLogos(orig).length >= 2, forms: (orig.forms || []).some((f) => f.src) ? 'swap' : FORM_SLOTS.has(slot) || orig.inputs.length ? 'keep' : 'hide' }); } catch (e) {
      return skip('PARAMETERIZE_FAILED', e.message, stage.relDir);
    }
    // a footer/navbar shows the owner's routes (plan sitemap), never the design's demo menu
    const fl = fillLinks(stage.entry, p.code, links, slot);
    fs.writeFileSync(entryAbs, fl.code);
    const b = bind(orig, p, { placeholder: hasPublic ? PLACEHOLDER : null, brand: brandName(root) });
    if (fl.filled.length) b.hidden.push(...fl.filled.map((f) => (f.demoHidden ? `${f.array}: the design's demo ${f.kind} hidden (${f.demoHidden}) — no menu in your plan` : `${f.array}: ${f.kind} from your plan (${f.count})`)));
    if (fl.filled.some((f) => f.count)) carryPlanLinks(b, links, orig);
    // fit gate: a variant that would throw away most of the owner's words is not offered
    const gate = opts.noFitGate ? null : fitGate(kind, origCount, b);
    if (gate) return skip('POOR_FIT', gate, stage.relDir);
    fit = b;
    fit.demoVisual = demoTexts(root, stage.relDir, []).length;
    for (const f of fs.readdirSync(path.join(root, stage.relDir))) {
      if (!/\.(tsx|jsx)$/.test(f)) continue;
      const fp = path.join(root, stage.relDir, f);
      const before = fs.readFileSync(fp, 'utf8');
      const after = markDemo(f, before);
      if (after !== before) fs.writeFileSync(fp, after);
    }
    stage.ownerTexts = orig.units.map((x) => x.text).concat(orig.lists.flatMap((l) => l.items.flatMap((it) => it.units.map((u) => u.text))), linkTexts(links));
    usage = `<${local}${contentProp(p.prop, b.props)} />`;
    stage.prop = p.prop;
    stage.removedChrome = p.removed;
  } else {
    // a wrapper (a card that renders its children): the owner's content goes inside, every word of it — and the
    // design's own words kept in props beside it ("Acme", "Case Study", "Get Started") are emptied, not shown
    const own = new Set(el.openingElement.attributes.filter((a) => a.type === 'JSXAttribute').map((a) => a.name.name));
    const demoProps = defaultPropsOf(stage.entry, entryCode, stage.export).filter((d) => !own.has(d.propName));
    usage = primitiveUsage(code, el, local, entryCode, demoProps.map((d) => `${d.propName}={${d.role === 'bullets' ? '[]' : '""'}}`));
    fit = { carried: orig.units.concat(orig.images), dropped: [], demo: [], hidden: demoProps.map((d) => `demo ${d.propName}: ${d.demo} (emptied)`), demoVisual: 0 };
  }
  const v = {
    idx: 0, id: cand.id, r: cand.r, n: cand.n, t: cand.t, lic: cand.lic || 'MIT', slot: cand.slot, generated: !!cand.ai, draft: cand.draft || null,
    slug: stage.slug, dir: stage.relDir, entry: stage.entry, spec: stage.spec, export: stage.export, local, usage,
    deps: stage.deps, missingDeps: stage.missingDeps, sourceUrl: stage.sourceUrl, prop: stage.prop || null,
    css: itemCss({ css: stage.css, cssVars: stage.cssVars }, id + '-' + stage.slug) || null,
    fit: { carried: fit.carried.length, of: origCount, dropped: fit.dropped, demo: fit.demo.map((d) => d.text).slice(0, 6), hidden: fit.hidden || [], demoVisual: fit.demoVisual || 0 },
    ownerTexts: stage.ownerTexts || [],
    removedChrome: stage.removedChrome || [],
  };
  if (cand.ai) v.aiItem = cand;                                   // More re-stages it from the draft's own files
  if (stage.missingDeps.length) return { held: v };
  // checked as it is staged: a design that would break the page makes room for the next candidate
  const why = opts.checkImports === false ? null : checkImports(root, [v]).bad.get(v);
  if (why) return skip('BROKEN_IMPORT', why, stage.relDir);
  return { v };
}

/** The bare packages a staged variant imports: [{spec, names}] (named imports plus `NS.x` reads of a namespace import). */
export function stagedImports(root, v) {
  const list = [];
  let files = [];
  try { files = fs.readdirSync(path.join(root, v.dir)); } catch { return list; }
  for (const f of files) {
    if (!/\.(tsx|ts|jsx|js|mjs)$/.test(f)) continue;
    const code = fs.readFileSync(path.join(root, v.dir, f), 'utf8');
    let ast;
    try { ast = parse(f, code); } catch { continue; }
    const ns = new Map();
    for (const st of ast.program.body) {
      if (st.type !== 'ImportDeclaration' || st.importKind === 'type') continue;
      const spec = st.source.value;
      if (/^(\.|@\/|~\/|node:)/.test(spec) || /\.(css|scss|svg|png|jpe?g|webp|json)$/.test(spec)) continue;
      const names = st.specifiers.filter((x) => x.type === 'ImportSpecifier' && x.importKind !== 'type')
        .map((x) => x.imported.name || x.imported.value);
      const item = { spec, names };
      for (const x of st.specifiers) if (x.type === 'ImportNamespaceSpecifier') ns.set(x.local.name, item);
      list.push(item);
    }
    // `import * as TogglePrimitive from 'radix-ui/toggle'` then `TogglePrimitive.Root`: Root must exist too
    if (ns.size) {
      walk(ast, (n) => {
        // P.Trigger() and <P.Root> (a JSXMemberExpression) both read a name the module must export
        const js = n.type === 'MemberExpression' && !n.computed && n.object.type === 'Identifier' && n.property.type === 'Identifier';
        const jsx = n.type === 'JSXMemberExpression' && n.object.type === 'JSXIdentifier';
        if ((js || jsx) && ns.has(n.object.name)) {
          const item = ns.get(n.object.name);
          if (!item.names.includes(n.property.name)) item.names.push(n.property.name);
        }
        return true;
      });
    }
  }
  return list;
}

/**
 * Load every package a staged variant imports, from the project (the resolution the app will do), in ONE child
 * process, and check each named import exists. Not found or a missing name = the variant would break the build.
 * A package that cannot load outside a browser is "unknown" and never counts against a variant.
 */
export function checkImports(root, variants) {
  const need = new Map();
  const uses = new Map();
  for (const v of variants) {
    const list = stagedImports(root, v);
    for (const { spec, names } of list) {
      const set = need.get(spec) || new Set();
      names.forEach((n) => set.add(n));
      need.set(spec, set);
    }
    uses.set(v, list);
  }
  const bad = new Map();
  if (!need.size) return { bad };
  if (!fs.existsSync(path.join(root, 'node_modules'))) return { bad, skipped: 'no node_modules: nothing installed to check against' };
  const want = JSON.stringify([...need].map(([s, n]) => [s, [...n]]));
  const script = `import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
const req = createRequire(process.cwd() + '/package.json');
// installed = a node_modules/<pkg> up the tree (how node and bundlers resolve); present but not loadable here = unknown
const present = (pkg) => { for (let d = process.cwd(); ; d = path.dirname(d)) { if (fs.existsSync(path.join(d, 'node_modules', pkg, 'package.json'))) return true; if (path.dirname(d) === d) return false; } };
const pkgOf = (s) => s.startsWith('@') ? s.split('/').slice(0, 2).join('/') : s.split('/')[0];
// a package the import itself needs and nobody installed (radix-ui/toggle re-exports @radix-ui/react-toggle)
const depOf = (e, pkg) => { const m = /Cannot find (?:package|module) '([^'./\\\\][^']*)'/.exec(String(e && e.message)); if (!m || /[:\\\\]/.test(m[1])) return null; const d = pkgOf(m[1]); return d !== pkg && !present(d) ? d : null; };
const want = ${want}; const out = {};
const judge = (m, names) => { const miss = names.filter((n) => !(n in m) && !(m && m.default && typeof m.default === 'object' && n in m.default)); return miss.length ? { missing: miss } : { ok: true }; };
for (const [s, names] of want) {
  const pkg = pkgOf(s);
  let dep = null;
  try { out[s] = judge(await import(s), names); continue; } catch (e) { dep = depOf(e, pkg); out[s] = { unknown: String(e && e.message).slice(0, 120) }; }
  // bundlers resolve more than strict ESM does (next/link has no export map): CommonJS resolution decides
  let found = null;
  try { found = req.resolve(s); } catch (e) { if (!present(pkg)) out[s] = { notFound: true }; }
  if (found) { try { out[s] = judge(req(s), names); dep = null; } catch (e) { dep = dep || depOf(e, pkg); out[s] = { unknown: String(e && e.message).slice(0, 120) }; } }
  if (dep && out[s].unknown) out[s] = { brokenDep: dep };
}
process.stdout.write(JSON.stringify(out));`;
  const r = spawnSync(process.execPath, ['--input-type=module', '-e', script], { cwd: root, encoding: 'utf8', timeout: 90000 });
  let res = null;
  try { res = JSON.parse(String(r.stdout || '').trim().split('\n').pop()); } catch { return { bad, error: String(r.stderr || '').slice(-300) }; }
  for (const [v, list] of uses) {
    const why = [];
    for (const { spec, names } of list) {
      const x = res[spec] || {};
      if (x.notFound) why.push(`${spec} is not installed`);
      else if (x.brokenDep) why.push(`${spec} needs ${x.brokenDep}, which is not installed`);
      else if (x.missing) {
        const m = names.filter((n) => x.missing.includes(n));
        if (m.length) why.push(`${spec} has no ${m.join(', ')}`);
      }
    }
    if (why.length) bad.set(v, [...new Set(why)].join('; '));
  }
  return { bad, checked: need.size };
}

// ------------------------------------------------------------------ the page still builds (or nothing stays)

const BUILD_ERR = /(is a self-closing tag|Element type is invalid|Hydration failed|Cannot read propert(?:y|ies) of|Module not found|Can't resolve|Failed to resolve import|Pre-transform error|Build Error|Failed to compile|Export [\w$]+ doesn't exist|is not exported from|doesn't exist in target module|Unexpected token|Expected .* got|SyntaxError|ReferenceError: [\w$]+ is not defined)/;

const REACT_ERR = /^(is a self-closing tag|Element type is invalid|Hydration failed|Cannot read propert)/;

/** GET a page from the dev server (it compiles on request). {status, text} or {status: 0} when unreachable. */
export function probePage(url, page = '/', timeoutMs = 90000) {
  const u = new URL(page || '/', url);
  const host = (u.hostname === '127.0.0.1' ? 'localhost' : u.hostname) + (u.port ? ':' + u.port : '');
  return new Promise((resolve) => {
    const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname + u.search, method: 'GET',
      headers: { host, accept: 'text/html', 'accept-encoding': 'identity' }, timeout: timeoutMs }, (res) => {
      let text = '';
      res.setEncoding('utf8');
      res.on('data', (c) => { if (text.length < 3e6) text += c; });
      res.on('end', () => resolve({ status: res.statusCode, text }));
    });
    req.on('timeout', () => { req.destroy(); resolve({ status: 0, text: 'timeout' }); });
    req.on('error', (e) => resolve({ status: 0, text: String(e.message) }));
    req.end();
  });
}

export function buildError(pr) {
  if (!pr || pr.status === 0) return null;
  const m = BUILD_ERR.exec(pr.text || '');
  if (pr.status < 500 && !(m && /Module not found|Can't resolve|Build Error|Failed to compile/.test(m[1]))) return null;
  if (!m && pr.status < 500) return null;
  // Next's error page carries the render error in an attribute (<template data-next-error-message="…">): markup
  // stripping would erase it, so read it from there
  const tpl = /data-next-error-message=[\\]*"([^"\\]+)/.exec(pr.text || '');
  if (tpl && (!m || REACT_ERR.test(m[1]))) return tpl[1].replace(/&#x27;|&#39;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim();
  const at = m ? m.index : 0;
  const from = Math.max(0, at - 60);
  const lead = from ? (pr.text || '').slice(from, at).search(/[\s"'>(]/) + 1 : 0;   // start on a word, not mid-path
  return (pr.text || '').slice(from + Math.max(0, lead), at + 240).replace(/\\n|\n/g, ' ').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim() || `HTTP ${pr.status}`;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Load the page until the dev server has compiled what is on disk now: the session's wrapper is in the HTML
 * (`want` = its id), or a build error is, or (`want` = null) the page is clean again. A dev server's file watcher
 * lags the write, so the first answer can be the page from BEFORE the change — never proof of anything.
 */
export async function probeUntil(url, page, want, deadlineMs = 25000) {
  const t0 = Date.now();
  let wait = 300;
  for (;;) {
    const p = await probePage(url, page);
    if (p.status === 0) return p;
    const err = buildError(p);
    if (want ? (err || (p.text || '').includes(`data-dh-session="${want}"`)) : !err) return p;
    if (Date.now() - t0 > deadlineMs) return { ...p, late: true };
    await sleep(wait);
    wait = Math.min(wait * 2, 2500);
  }
}

/**
 * Vite renders in the browser, so the page's HTML never shows a variant: ask Vite for the modules instead. The
 * edited file (until it carries this session — the watcher lags the write, like any dev server), then each design's
 * own entry: Vite resolves a module's imports when it is requested (a missing one is a 500 naming the file), and the
 * request also warms its dependency optimizer before the browser loads anything.
 */
export async function probeVite(url, root, id, deadlineMs = 25000, { clean = false } = {}) {
  const s = loadSession(root, id);
  const t0 = Date.now();
  let wait = 300;
  for (;;) {
    const p = await probePage(url, '/' + s.file);
    if (p.status === 0) return p;
    const err = buildError(p);
    if (clean ? !err : err) return p;
    if (!clean && (p.text || '').includes(id)) break;
    if (Date.now() - t0 > deadlineMs) return { ...p, late: true };
    await sleep(wait);
    wait = Math.min(wait * 2, 2500);
  }
  for (const v of s.variants) {
    const p = await probePage(url, '/' + v.entry);
    if (buildError(p)) return p;
  }
  return { status: 200, text: `data-dh-session="${id}"` };
}

/** Which variants a build error points at: their folder in the error's import trace, else the module it cannot load. */
export function culpritsOf(root, variants, text) {
  // The error's own message and stack come first: a Next 500 page also lists every client module on the page, so a design that
  // only appears there (it renders fine) must not be blamed for a sibling's error.
  const own = [...String(text).matchAll(/data-next-error-(?:message|stack)=(\\*)"((?:(?!\1")[^])*)/g)].map((m) => m[2]).join('\n');
  if (own) {
    const hit = variants.filter((v) => own.includes(v.slug) || own.includes(v.dir));
    if (hit.length) return hit;
  }
  const named = variants.filter((v) => text.includes(v.slug) || text.includes(v.dir));
  if (named.length) return named;
  const mods = new Set();
  for (const m of text.matchAll(/Can(?:'|\\u0027|&#x27;)t resolve (?:'|\\u0027|&#x27;|\\")([^'"\\&]+)/g)) mods.add(m[1]);
  // the failing module as the bundler names it (./node_modules/radix-ui/dist/toggle.mjs:2:1) — never a stack frame
  for (const m of text.matchAll(/\.\/node_modules\/((?:@[\w.-]+\/)?[\w.-]+)\/(?:dist\/|esm\/|lib\/)?([\w.-]+)?[^\s:'"]*:\d+:\d+/g)) {
    mods.add(m[1]);
    if (m[2]) mods.add(m[1] + '/' + m[2].replace(/\.(m?js|cjs)$/, ''));
  }
  for (const f of ['next', 'react', 'react-dom', 'vite', 'webpack']) mods.delete(f);
  if (!mods.size) return [];
  const pkgOf = (x) => (x.startsWith('@') ? x.split('/').slice(0, 2).join('/') : x.split('/')[0]);
  return variants.filter((v) => stagedImports(root, v).some(({ spec }) => mods.has(spec) || mods.has(pkgOf(spec))));
}

/**
 * open() + proof the page still builds. With a dev URL: the page is loaded before (baseline) and after the
 * variants are written — after = once the dev server shows THIS session's wrapper or an error; a new build error
 * restores the file at once, drops the variants the error points at and tries again without them (twice at most).
 * The owner never keeps a broken page.
 */
export async function openVerified(rootIn, opts, { url, page, deadlineMs = 25000 } = {}) {
  // no dev server known: staged, but nobody loaded the page — said, so an `ok` is never read as "the page works"
  if (!url) return { ...(await open(rootIn, opts)), verified: false, note: 'no dev server known, so the page was not checked: pass --url http://127.0.0.1:<port> (or start it with `dh dev start`), or load the page yourself before showing it' };
  const prof0 = detectProject(rootIn);
  const root = prof0.root;
  const vite = prof0.framework === 'vite';
  const base = await probePage(url, page);
  const baseErr = buildError(base);
  let exclude = [...(opts.exclude || [])];
  const dropped = [];
  const kept = [];                                               // installed by a rolled-back attempt: still there
  for (let attempt = 0; attempt < 3; attempt++) {
    let s;
    try { s = await open(rootIn, { ...opts, exclude }); } catch (e) {
      // the designs that broke the page were dropped and nothing else fits: that is the news, not "no candidates"
      if (!dropped.length || !['NO_CANDIDATES', 'NO_VARIANTS'].includes(e.code)) throw e;
      throw new TryonError('BUILD_BROKE', `${dropped.length} design(s) broke the page (${dropped.map((d) => d.id).join(', ')}), so your file was restored; nothing else fits this element. ${e.message}`,
        { restored: true, dropped, installedKept: kept, ...(e.skipped ? { skipped: e.skipped } : {}) });
    }
    if (kept.length) {
      const full = loadSession(root, s.id);
      full.installed = [...new Set([...(full.installed || []), ...kept])];
      saveSession(root, full);
      s.installed = full.installed;
    }
    if (baseErr) return { ...s, verified: false, note: 'the page already had an error before the swap — not checked: ' + baseErr.slice(0, 160) };
    if (base.status === 0) return { ...s, verified: false, note: 'the dev server did not answer — not checked' };
    const after = vite ? await probeVite(url, root, s.id, deadlineMs) : await probeUntil(url, page, s.id, deadlineMs);
    const err = buildError(after);
    if (!err) {
      const shown = (after.text || '').includes(`data-dh-session="${s.id}"`);
      return { ...s, verified: shown, ...(shown ? {} : { note: `the page ${page || '/'} did not show the variants within ${Math.round(deadlineMs / 1000)}s — the build was not checked` }), ...(dropped.length ? { dropped } : {}) };
    }
    const full = loadSession(root, s.id);
    const culprits = culpritsOf(root, full.variants, after.text || '');
    const d = discard(root, s.id, { reason: 'build' });
    for (const p of d.installedKept || []) if (!kept.includes(p)) kept.push(p);
    if (vite) await probeVite(url, root, s.id, deadlineMs, { clean: true });
    else await probeUntil(url, page, null, deadlineMs);          // the dev server rebuilt the restored file
    if (!culprits.length) {
      throw new TryonError('BUILD_BROKE', `the page stopped building with these variants, so your file was restored at once. The error: ${err.slice(0, 300)}`,
        { restored: true, dropped, installedKept: kept });
    }
    for (const v of culprits) dropped.push({ id: v.id, why: err.slice(0, 200) });
    exclude = exclude.concat(culprits.map((v) => v.id));
  }
  throw new TryonError('BUILD_BROKE', 'every variant tried broke the page build — your file is restored', { restored: true, dropped, installedKept: kept });
}

/**
 * More: the next batch from the pool for an open session. The variants the owner has seen come back in their places
 * (an AI draft too, from its own files), then `batch` new designs after them — never one already offered or refused.
 * Nothing is discarded when the pool is spent or the session is full: the owner keeps comparing what they have.
 * { url, page } (a running dev server) proves the page still builds, like every open.
 */
export async function more(rootIn, id, { batch = 4, probe, onProgress, url, page, deadlineMs } = {}) {
  const prof = detectProject(rootIn);
  const root = prof.root;
  const s = loadSession(root, id);
  if (s.state !== 'open') throw new TryonError('SESSION_CLOSED', `session ${id} is ${s.state}`);
  const n = Math.max(1, Math.min(12, Number(batch) || 4));
  const catalog = loadCatalog();
  const byId = new Map(catalog.map((c) => [c.id, c]));
  const shown = s.variants.slice().sort((a, b) => a.idx - b.idx).map((v) => (v.generated ? v.aiItem : byId.get(v.id))).filter(Boolean);
  const room = MAX_VARIANTS - s.variants.length;
  if (room <= 0) throw new TryonError('TOO_MANY_VARIANTS', `this element already shows ${s.variants.length} variants, the most one try holds: keep one, or discard and pick again`, { max: MAX_VARIANTS });
  const tried = [...new Set((s.tried || []).concat(s.variants.map((v) => v.id)))];
  const fresh = rank(catalog, { slot: s.slot, prof, exclude: tried, registry: s.registry || null }).items;
  if (!fresh.length) throw new TryonError('POOL_EMPTY', `every ${s.slot} design in the pool has already been shown for this element (${tried.length} tried): keep one, or ask AI to draft one`, { pool: s.pool || null });
  discard(root, id, { reason: 'more' });
  const r = await openVerified(root, { file: s.file, line: s.line, col: s.col, slot: s.slot, count: shown.length + Math.min(n, room),
    candidates: shown.concat(fresh), first: shown.map((c) => c.id), tried, registry: s.registry || null, probe, onProgress }, { url, page, deadlineMs });
  const back = r.variants.filter((v) => v.idx > 0 && shown.some((c) => c.id === v.id)).length;
  const added = r.variants.length - 1 - back;
  return { ...r, added, startAt: added ? back + 1 : 1 };
}

// text compared the way a browser shows it may differ from the source: case (CSS uppercase), spacing, split words
const squash = (t) => String(t || '').replace(/\s+/g, '').toLowerCase();
/** The static text an element renders FIRST (its innerText starts with it); '' when an expression comes first. */
function leadText(el) {
  let out = '';
  let stop = false;
  walk(el, (m) => {
    if (stop || out.length > 80) return false;
    if (m.type === 'JSXText') out += m.value;
    else if (m.type === 'JSXExpressionContainer') {
      if (m.expression.type === 'StringLiteral') out += m.expression.value;
      else if (m.expression.type !== 'JSXEmptyExpression') { stop = true; return false; }
      return false;
    } else if (m.type === 'JSXAttribute') return false;
    return true;
  });
  return squash(out);
}
function allText(el) {
  let txt = '';
  walk(el, (m) => { if (m.type === 'JSXText') txt += m.value; else if (m.type === 'StringLiteral' && txt.length < 400) txt += m.value; return txt.length < 800; });
  return squash(txt);
}
const HOST = /^[a-z][a-z0-9-]*$/;
// the page names a tag (`a`, `section`) or a component (`Button`); the source may be a component that renders
// that tag (<Link> is an <a> on the page): only a host element named otherwise is surely something else
function tagFits(el, tag, strict = false) {
  const name = jsxName(el.openingElement.name);
  if (!tag || tag === 'component' || name === tag) return true;
  if (HOST.test(name)) return false;
  return HOST.test(tag) || !strict;
}
/** Is `el` the element the owner clicked? No only when sure: another host tag, or text that starts differently. */
export function fitsHint(el, hint) {
  if (!hint) return true;
  const tag = String(hint.tag || '');
  if (!tagFits(el, tag)) return false;
  const want = squash(hint.text);
  const lead = leadText(el);
  if (lead.length < 6 || want.length < 6) return true;
  const k = Math.min(lead.length, want.length, 24);
  return want.slice(0, k) === lead.slice(0, k);
}

/**
 * The page's stamp is stale (the file moved under it: a try-on session added and removed import lines, an edit):
 * find the element again by what it is — its tag and the start of its text — nearest to where it was.
 * One unambiguous match or nothing (a wrong element is worse than a clear "reload").
 */
export function relocate(ast, code, hint, nearLine = 0) {
  const tag = String(hint && hint.tag || '');
  const want = squash(hint && hint.text).slice(0, 40);
  if (!tag || want.length < 4) return null;
  const hits = [];
  walk(ast, (n) => {
    if (n.type === 'JSXElement' && tagFits(n, tag, true)) {
      const lead = leadText(n);
      const k = Math.min(lead.length, want.length);
      if ((lead.length >= 6 && want.slice(0, k) === lead.slice(0, k)) || allText(n).includes(want.slice(0, 30))) hits.push(n);
    }
    return true;
  });
  // the innermost matching element per branch (a section inside a section with the same text: the inner one)
  const inner = hits.filter((h) => !hits.some((o) => o !== h && o.start >= h.start && o.end <= h.end));
  if (!inner.length) return null;
  inner.sort((a, b) => Math.abs(lineCol(code, a.start).line - nearLine) - Math.abs(lineCol(code, b.start).line - nearLine));
  if (inner.length > 1 && Math.abs(lineCol(code, inner[0].start).line - nearLine) === Math.abs(lineCol(code, inner[1].start).line - nearLine)) return null;
  return inner[0];
}

/**
 * The element the owner picked: the one at file:line:col when it is what they clicked (`hint`), else the same
 * element found again (the page was older than the file). {el, line, col, relocated} or null.
 */
/**
 * `<Button asChild><Link>…</Link></Button>`: the page shows ONE button, styled by the component that wraps it; its
 * props (stamp included) land on the child, so the pick names the child. The element that styles it is the wrapper.
 */
export function styledBy(ast, el) {
  let hit = null;
  walk(ast, (n) => {
    if (hit) return false;
    if (n.type === 'JSXElement' && n.start < el.start && el.end <= n.end) {
      const kids = (n.children || []).filter((c) => !(c.type === 'JSXText' && !c.value.trim()));
      if (kids.length === 1 && kids[0] === el && attr(n, 'asChild')) hit = n;
    }
    return true;
  });
  return hit || el;
}

export function pickElement(ast, code, line, col, hint = null) {
  const at = findElementAt(ast, code, Number(line), Number(col));
  if (at && fitsHint(at, hint)) return { el: at, line: Number(line), col: Number(col), relocated: false };
  const el = hint ? relocate(ast, code, hint, Number(line)) : null;
  if (!el) return null;
  const lc = lineCol(code, el.start);
  return { el, line: lc.line, col: lc.col, relocated: true };
}

export function publicSession(s) {
  return {
    id: s.id, state: s.state, file: s.file, line: s.line, slot: s.slot, shown: s.shown, hidden: s.hidden,
    variants: [{ idx: 0, t: 'Original', r: 'yours' }].concat(s.variants.map((v) => ({
      idx: v.idx, id: v.id, t: v.t, r: v.r, lic: v.lic, fit: v.fit, deps: v.deps, source: v.sourceUrl, removedChrome: v.removedChrome, generated: !!v.generated,
    }))),
    skipped: s.skipped, installed: s.installed,
    ...(s.warning ? { warning: s.warning } : {}),
    pool: s.pool || null, max: MAX_VARIANTS,
    // the owner's own words (the overlay's auto-check looks for them on the page when a variant is flagged)
    owner: ((s.variants[0] && s.variants[0].ownerTexts) || []).slice(0, 80).map((t) => String(t).slice(0, 200)),
  };
}

/**
 * The fit gate: why a staged design is not offered, or null. A section must carry at least half of the owner's
 * content pieces; a card or a button all of them (one that drops their title or button — a fitness-rings widget, a
 * music player — is a different thing, not a variant of theirs); and any design must have a place for the owner's
 * form (a newsletter whose email field vanished leaves a dead "Subscribe" link).
 */
/**
 * A footer/navbar shows the plan's menu in place of the design's: the owner's own links that menu holds (same
 * route or same label) are on the page, so they count as carried, not dropped — before the fit gate weighs them.
 */
export function carryPlanLinks(b, links, orig) {
  if (!links) return b;
  const norm = (x) => String(x || '').trim().toLowerCase().replace(/(.)\/+$/, '$1');
  const shown = [...(links.header || []), ...(links.footerCols || []).flatMap((c) => c.links || [])];
  const hrefs = new Set(shown.map((l) => norm(l.href)));
  const labels = new Set(shown.map((l) => norm(l.label)));
  // the owner's link as written: "/menu", '/menu' or `/menu` (a template with ${…} is not a fixed route)
  const hrefOf = (text) => {
    const u = orig.units.find((x) => x.role === 'action' && x.text === text);
    const m = u && typeof u.href === 'string' && u.href.trim().match(/^(["'`])([^"'`$]*)\1$/);
    return m ? m[2] : null;
  };
  const keep = [];
  for (const d of b.dropped) {
    if (d.role === 'action' && (labels.has(norm(d.text)) || hrefs.has(norm(hrefOf(d.text))))) b.carried.push({ ...d, via: 'plan menu' });
    else keep.push(d);
  }
  b.dropped = keep;
  return b;
}

/** A usage with nothing inside it (`<Pricing />`): the designs have no words to carry — say where the words are (F21). */
export function emptyUsage(el, orig) {
  if (contentCount(orig) > 0 || (orig.inputs && orig.inputs.length) || (el.children && el.children.length)) return null;
  const tag = jsxName(el.openingElement.name);
  return { code: 'EMPTY_USAGE', message: `<${tag} /> has no content here — its words live in its own file, so no design can carry them. Open ${tag}'s file and try its outer element instead.` };
}

export function fitGate(kind, origCount, b) {
  if (b.lost) return `has no place for your ${b.lost}`;
  const need = kind === 'block' ? Math.ceil(origCount / 2) : origCount;
  if (origCount >= 1 && b.carried.length < need) return `carries ${b.carried.length}/${origCount}`;
  return null;
}

/** Why nothing could be shown, in the owner's words: "none has room for your content" beats a code. */
export function noVariantsWhy(skipped, slot) {
  const real = skipped.filter((s) => s.why !== 'FETCH_FAILED');
  const poor = real.filter((s) => s.why === 'POOR_FIT');
  if (poor.length && poor.length === real.length) {
    const lost = poor.map((s) => /has no place for your (\w+)/.exec(s.detail || '')).filter(Boolean);
    if (lost.length === poor.length) return `none of the ${poor.length} ${slot} design(s) has a place for your ${lost[0][1]} (it would stop working): pick another kind of section in the list, or ask AI to draft one`;
    const best = poor.map((s) => /(\d+)\/(\d+)/.exec(s.detail || '')).filter(Boolean).sort((a, b) => b[1] / b[2] - a[1] / a[2])[0];
    return `none of the ${poor.length} ${slot} design(s) has room for your content${best ? ` (the closest keeps ${best[1]} of your ${best[2]} pieces)` : ''}: pick another kind of section in the list, or ask AI to draft one`;
  }
  if (!real.length && skipped.length) return `the ${slot} designs could not be downloaded (network?): try again, or pick another kind of section`;
  return 'no candidate could be staged';
}

/**
 * Local names the entry imports from brand-logo files. A design's demo brands are never shown as the owner's: its
 * logo row takes the owner's own logos when they have some, and is hidden otherwise — in a logo cloud too.
 */
export function logoLocalsFor(stage, entryCode) {
  const out = [];
  if (!stage.logoFiles || !stage.logoFiles.length) return out;
  for (const st of parse(stage.entry, entryCode).program.body) {
    if (st.type !== 'ImportDeclaration') continue;
    const base = path.posix.basename(st.source.value);
    if (stage.logoFiles.some((f) => f.replace(/\.(tsx|ts|jsx|js)$/, '') === base)) for (const sp of st.specifiers) out.push(sp.local.name);
  }
  return out;
}

/** Make variant `idx` the visible one in source (headless / persistence). */
export function show(rootIn, id, idx) {
  const root = path.resolve(rootIn);
  const s = loadSession(root, id);
  if (s.state !== 'open') throw new TryonError('SESSION_CLOSED', `session ${id} is ${s.state}`);
  const abs = path.join(root, s.file);
  const code = fs.readFileSync(abs, 'utf8');
  const ast = parse(s.file, code);
  const w = findWrapper(ast, id);
  if (!w) throw new TryonError('WRAPPER_MISSING', 'the variant wrapper is gone from ' + s.file);
  const edits = [];
  for (const v of variantChildren(w)) {
    const i = Number(attr(v, 'data-dh-variant').value.value);
    const st = attr(v, 'style');
    if (st) edits.push({ start: st.start, end: st.end, text: `style={{ display: "${i === Number(idx) ? 'contents' : 'none'}" }}` });
  }
  edits.sort((a, b) => b.start - a.start);
  let out = code;
  for (const e of edits) out = out.slice(0, e.start) + e.text + out.slice(e.end);
  fs.writeFileSync(abs, out);
  s.shown = Number(idx);
  s.shaAfter = sha(Buffer.from(out));
  saveSession(root, s);
  return publicSession(s);
}

function removeMarkedImports(code, id, keepLocal, newSpec) {
  return code.split('\n').filter((line) => {
    if (!line.includes(`// dh-tryon:${id}`)) return true;
    return keepLocal && new RegExp(`\\b${keepLocal}\\b`).test(line);
  }).map((line) => {
    if (!line.includes(`// dh-tryon:${id}`)) return line;
    let l = line.replace(` // dh-tryon:${id}`, '');
    if (newSpec) l = l.replace(/from\s+(["'])[^"']+\1/, `from ${JSON.stringify(newSpec)}`);
    return l;
  }).join('\n');
}

function referencedByOtherOpen(root, dir, exceptId) {
  return listSessions(root).some((o) => o.id !== exceptId && o.state === 'open' && o.variants.some((v) => v.dir === dir));
}

const SAFE_GLOBALS = new Set(['Date', 'Math', 'Intl', 'String', 'Number', 'JSON', 'undefined']);

/** Text, plain host markup and self-contained expressions (`© {new Date().getFullYear()}`) only:
 *  safe to inline into another file because nothing refers to the usage site's scope. */
function markupOnly(frag) {
  let ok = true;
  walk(frag, (n, parent, key) => {
    if (!ok) return false;
    if (n.type === 'JSXOpeningElement' && !/^[a-z]/.test(jsxName(n.name))) { ok = false; return false; }
    if (n.type === 'JSXSpreadAttribute') { ok = false; return false; }
    if (n.type === 'Identifier') {
      const isProp = parent && ((parent.type === 'MemberExpression' && key === 'property' && !parent.computed) || (parent.type === 'ObjectProperty' && key === 'key'));
      if (!isProp && !SAFE_GLOBALS.has(n.name)) { ok = false; return false; }
    }
    return true;
  });
  return ok;
}

/** Drop import specifiers nobody references any more; delete folder files nothing imports. */
export function pruneFolder(root, dirRel, entryRel) {
  const dir = path.join(root, dirRel);
  const files = () => fs.readdirSync(dir).filter((f) => /\.(tsx|ts|jsx|js)$/.test(f));
  for (let pass = 0; pass < 5; pass++) {
    let changed = false;
    for (const f of files()) {
      const p = path.join(dir, f);
      let code = fs.readFileSync(p, 'utf8');
      const ast = parse(f, code);
      const edits = [];
      for (const st of ast.program.body) {
        if (st.type !== 'ImportDeclaration' || !st.specifiers.length) continue;
        const body = code.slice(0, st.start) + code.slice(st.end);
        const used = st.specifiers.filter((sp) => new RegExp(`(^|[^\\w$.])${sp.local.name}([^\\w$]|$)`).test(body));
        if (used.length === st.specifiers.length) continue;
        const end = code[st.end] === '\n' ? st.end + 1 : st.end;
        if (!used.length) { edits.push({ start: st.start, end, text: '' }); continue; }
        const def = used.find((sp) => sp.type === 'ImportDefaultSpecifier');
        const ns = used.find((sp) => sp.type === 'ImportNamespaceSpecifier');
        const named = used.filter((sp) => sp.type === 'ImportSpecifier').map((sp) => code.slice(sp.start, sp.end));
        const parts = [def && def.local.name, ns && code.slice(ns.start, ns.end), named.length && `{ ${named.join(', ')} }`].filter(Boolean);
        edits.push({ start: st.start, end: st.end, text: `import ${st.importKind === 'type' ? 'type ' : ''}${parts.join(', ')} from ${code.slice(st.source.start, st.source.end)}` });
      }
      if (!edits.length) continue;
      edits.sort((x, y) => y.start - x.start);
      for (const e of edits) code = code.slice(0, e.start) + e.text + code.slice(e.end);
      parse(f, code);
      fs.writeFileSync(p, code);
      changed = true;
    }
    // files no other file in the folder imports (the entry is always kept)
    const imported = new Set();
    for (const f of files()) {
      for (const m of fs.readFileSync(path.join(dir, f), 'utf8').matchAll(/from\s+['"]\.\/([^'"]+)['"]/g)) imported.add(m[1].replace(/\.(tsx|ts|jsx|js)$/, ''));
    }
    for (const f of files()) {
      if (path.posix.join(dirRel, f) === entryRel) continue;
      if (!imported.has(f.replace(/\.(tsx|ts|jsx|js)$/, ''))) { fs.unlinkSync(path.join(dir, f)); changed = true; }
    }
    if (!changed) break;
  }
}

/**
 * Bake the kept variant: literal copy goes INTO the component, show/hide switches are resolved
 * (hidden demo buttons and logo rows are deleted, not left dormant), and whatever the usage still
 * has to pass (in-scope expressions like {t('x')}) stays a prop. Unused imports/files are pruned.
 */
export function bake(root, fileRel, local, variant) {
  const abs = path.join(root, fileRel);
  let code = fs.readFileSync(abs, 'utf8');
  const ast = parse(fileRel, code);
  let usageEl = null;
  walk(ast, (n) => {
    if (usageEl) return false;
    if (n.type === 'JSXElement' && jsxName(n.openingElement.name) === local) { usageEl = n; return false; }
    return true;
  });
  if (!usageEl || !variant.prop) return { baked: 0 };
  const a = attr(usageEl, variant.prop);
  const values = new Map();          // key -> { kind: 'string'|'text'|'bool'|'json', ... }
  const keepProps = [];
  if (a && a.value && a.value.type === 'JSXExpressionContainer' && a.value.expression.type === 'ObjectExpression') {
    for (const p of a.value.expression.properties) {
      if (p.type !== 'ObjectProperty') { keepProps.push(code.slice(p.start, p.end)); continue; }
      const k = p.key.name || p.key.value;
      const v = p.value;
      if (v.type === 'StringLiteral') values.set(k, { kind: 'string', value: v.value });
      else if (v.type === 'BooleanLiteral') values.set(k, { kind: 'bool', value: v.value });
      else if (v.type === 'NumericLiteral') values.set(k, { kind: 'number', value: v.value });
      else if (v.type === 'ArrayExpression' && v.elements.length && v.elements.every((x) => x && x.type === 'ObjectExpression' && markupOnly(x))) {
        values.set(k, { kind: 'list', raw: code.slice(v.start, v.end), node: v });
      }
      else if (v.type === 'ArrayExpression' && v.elements.every((x) => x && x.type === 'StringLiteral')) values.set(k, { kind: 'array', raw: code.slice(v.start, v.end) });
      else if (v.type === 'JSXFragment' && markupOnly(v)) {
        let txt = '';
        walk(v, (n) => { if (n.type === 'JSXText') txt += n.value; return true; });
        values.set(k, { kind: 'text', value: txt.replace(/\s+/g, ' ').trim(), raw: v.children.length ? code.slice(v.children[0].start, v.children[v.children.length - 1].end) : '' });
      } else keepProps.push(code.slice(p.start, p.end));
    }
  }
  const live = new Set(keepProps.map((kp) => kp.split(':')[0].trim()));
  const cAbs = path.join(root, variant.entry);
  let comp = fs.readFileSync(cAbs, 'utf8');
  const accRe = new RegExp(`^(?:${variant.prop}|\\w+\\.${variant.prop}\\?)\\.(\\w+)$`);
  const keyOf = (node) => { const m = accRe.exec(comp.slice(node.start, node.end).replace(/\s/g, '')); return m ? m[1] : null; };
  const cast = parse(variant.entry, comp);
  const edits = [];
  walk(cast, (n, parent) => {
    // show/hide: {cond && cond && (<el/>)}
    if (n.type === 'JSXExpressionContainer' && n.expression.type === 'LogicalExpression' && n.expression.operator === '&&') {
      const conds = [];
      let e = n.expression;
      while (e.type === 'LogicalExpression' && e.operator === '&&') { conds.unshift(e.right); e = e.left; }
      conds.unshift(e);
      const body = conds.pop();
      const parsed = conds.map((c) => (c.type === 'BinaryExpression' && /^[!=]==$/.test(c.operator) && c.right.type === 'BooleanLiteral' ? { key: keyOf(c.left), op: c.operator, lit: c.right.value } : null));
      if (parsed.length && parsed.every((c) => c && c.key) && (body.type === 'JSXElement' || body.type === 'JSXFragment') && !parsed.some((c) => live.has(c.key))) {
        const on = parsed.every((c) => {
          const v = values.has(c.key) ? values.get(c.key).value : undefined;
          return c.op === '!==' ? v !== c.lit : v === c.lit;
        });
        edits.push({ start: n.start, end: n.end, text: on ? '__DH_KEEP__' : '', node: body });
        return on;               // descend into kept bodies for their slots
      }
    }
    if (n.type === 'LogicalExpression' && n.operator === '??') {
      const k = keyOf(n.left);
      if (k && live.has(k)) {
        // a live prop keeps its fallback, but never the preview's demo marker
        const r = n.right;
        if (r.type === 'JSXElement' && attr(r, 'data-dh-demo')) {
          const inner = r.children.length ? comp.slice(r.children[0].start, r.children[r.children.length - 1].end) : '';
          edits.push({ start: r.start, end: r.end, text: `<>${inner}</>` });
        }
        return false;
      }
      if (!k) return true;
      const container = parent && parent.type === 'JSXExpressionContainer' ? parent : null;
      const lit = values.get(k);
      if (!container) {
        // an expression slot (bullets: `(content.bullets1 ?? [...])`): inline the owner's array
        if (lit && lit.kind === 'array') edits.push({ start: n.start, end: n.end, text: lit.raw });
        else if (!lit) edits.push({ start: n.start, end: n.end, text: comp.slice(n.right.start, n.right.end) });
        return false;
      }
      const inAttr = comp[container.start - 1] === '=';
      let text;
      if (lit && lit.kind === 'bool' && lit.value === false && !inAttr) text = '';   // an optional slot left empty
      else if (lit && lit.kind !== 'bool') {
        if (inAttr) text = JSON.stringify(lit.value);
        else text = lit.kind === 'string' ? (/[{}<>]/.test(lit.value) ? `{${JSON.stringify(lit.value)}}` : lit.value) : lit.raw;
      } else {
        const r = n.right;
        if (inAttr) text = r.type === 'StringLiteral' ? JSON.stringify(r.value) : `{${comp.slice(r.start, r.end)}}`;
        else if (r.type === 'JSXFragment' || (r.type === 'JSXElement' && attr(r, 'data-dh-demo'))) text = r.children.length ? comp.slice(r.children[0].start, r.children[r.children.length - 1].end) : '';
        else text = `{${comp.slice(r.start, r.end)}}`;
      }
      edits.push({ start: container.start, end: container.end, text });
      return false;
    }
    // list slots `((content.list1 ? merge : demo) as typeof demo)`: unbound -> the design's own data
    if (n.type === 'ConditionalExpression') {
      // resolve a whole chain statically: `content.x ? a : b` and `content.cols === 2 ? "…" : …`
      const verdict = (t) => {
        const k1 = keyOf(t);
        if (k1 && !live.has(k1)) return values.has(k1) ? !!values.get(k1).value : false;
        if (t.type === 'BinaryExpression' && t.operator === '===' && t.right.type === 'NumericLiteral') {
          const k2 = keyOf(t.left);
          if (k2 && !live.has(k2)) return values.has(k2) ? Number(values.get(k2).value) === t.right.value : false;
        }
        return null;
      };
      // a list slot with literal data: the owner's items are written INTO the design's own array
      // (fields the owner did not give — icons, ids — keep the design's values), then the switch goes
      const lk = keyOf(n.test);
      if (lk && values.has(lk) && values.get(lk).kind === 'list' && n.alternate.type === 'Identifier') {
        const arrName = n.alternate.name;
        let decl = null;
        walk(cast, (m) => {
          if (decl) return false;
          if (m.type === 'VariableDeclarator' && m.id.type === 'Identifier' && m.id.name === arrName) {
            let init = m.init;
            while (init && /^TS(As|Satisfies)Expression$/.test(init.type)) init = init.expression;
            if (init && init.type === 'ArrayExpression') decl = init;
            return false;
          }
          return true;
        });
        if (decl && decl.elements.length && decl.elements.every((e) => e && e.type === 'ObjectExpression')) {
          const ownerItems = values.get(lk).node.elements;
          const objSrc = (i) => {
            const demoEl = decl.elements[i % decl.elements.length];
            const own = ownerItems[i];
            // a field the owner did not fill was shown as the design's own words, dashed: it bakes back to the design's value
            const ownKeys = new Map(own.properties.filter((p) => !(p.value.type === 'JSXElement' && attr(p.value, 'data-dh-demo')))
              .map((p) => [p.key.name || p.key.value, code.slice(p.value.start, p.value.end)]));
            const parts = [];
            for (const p of demoEl.properties) {
              const key = p.type === 'ObjectProperty' ? (p.key.name || p.key.value) : null;
              if (key && ownKeys.has(key)) { parts.push(`${comp.slice(p.key.start, p.key.end)}: ${ownKeys.get(key)}`); ownKeys.delete(key); }
              else parts.push(comp.slice(p.start, p.end));
            }
            for (const [key, val] of ownKeys) parts.push(`${JSON.stringify(key)}: ${val}`);
            return `{ ${parts.join(', ')} }`;
          };
          const ind = indentAt(comp, decl.elements[0].start);
          // a design array read in several places (a navbar's desktop AND mobile menu) is several list slots over ONE
          // declaration: it is rewritten once, from the first slot; queuing it per slot overlaps the edits and corrupts it
          if (!edits.some((x) => x.start === decl.start && x.end === decl.end)) {
            edits.push({ start: decl.start, end: decl.end, text: `[\n${ownerItems.map((_, i) => ind + objSrc(i)).join(',\n')},\n${ind.slice(0, -2) || ''}]` });
          }
          const target = parent && parent.type === 'TSAsExpression' ? parent : n;
          edits.push({ start: target.start, end: target.end, text: arrName });
          return false;
        }
      }
      if (verdict(n.test) !== null) {
        let node = n;
        while (node.type === 'ConditionalExpression' && verdict(node.test) !== null) node = verdict(node.test) ? node.consequent : node.alternate;
        const target = parent && parent.type === 'TSAsExpression' && keyOf(n.test) ? parent : n;
        edits.push({ start: target.start, end: target.end, text: comp.slice(node.start, node.end) });
        return false;
      }
    }
    return true;
  });
  // apply innermost-first: a kept wrapper body may contain slot edits
  edits.sort((x, y) => y.start - x.start || x.end - y.end);
  const applied = [];
  for (const e of edits) {
    if (applied.some((o) => o.start <= e.start && e.end <= o.end && o !== e && o.text === '')) continue;
    if (e.text === '__DH_KEEP__') {
      // unwrap: keep the body with every nested edit already applied
      // top-level edits already applied inside this body (a nested unwrap absorbed its own children)
      const inner = applied.filter((o) => o.start >= e.node.start && o.end <= e.node.end);
      const shift = inner.reduce((acc, o) => acc + (o.text.length - (o.end - o.start)), 0);
      const bodyText = comp.slice(e.node.start, e.node.end + shift);
      comp = comp.slice(0, e.start) + bodyText + comp.slice(e.end + shift);
      for (const o of inner) applied.splice(applied.indexOf(o), 1);
      applied.push({ start: e.start, end: e.end, text: bodyText });
      continue;
    }
    comp = comp.slice(0, e.start) + e.text + comp.slice(e.end);
    for (const o of applied.filter((x) => x.start >= e.start && x.end <= e.end)) applied.splice(applied.indexOf(o), 1);
    applied.push(e);
  }
  // `unoptimized` was a preview guard for remote demo images; a local src gets Next's optimizer back
  comp = comp.replace(/(<\w+) unoptimized(\s+src="\/[^"]*(?<!\.svg)")/g, '$1$2');
  if (!keepProps.length) {
    comp = comp.replace(`{ ${variant.prop} = {} }: { ${variant.prop}?: Record<string, any> } = {}`, '')
      .replace(`{ ${variant.prop} = {} } = {}`, '')
      .replace(` ${variant.prop} = {},`, '')
      .replace(` & { ${variant.prop}?: Record<string, any> }`, '');
  }
  try { parse(variant.entry, comp); } catch (e) {
    if (process.env.DH_DEBUG_BAKE) fs.writeFileSync(process.env.DH_DEBUG_BAKE, comp);
    throw e;
  }
  fs.writeFileSync(cAbs, comp);
  pruneFolder(root, path.posix.dirname(variant.entry), variant.entry);
  // the usage keeps only live props
  if (a) {
    const newAttr = keepProps.length ? `${variant.prop}={{ ${keepProps.join(', ')} }}` : '';
    const start = keepProps.length ? a.start : (code[a.start - 1] === ' ' ? a.start - 1 : a.start);
    code = code.slice(0, start) + newAttr + code.slice(a.end);
    parse(fileRel, code);
    fs.writeFileSync(abs, code);
  }
  return { baked: values.size, live: keepProps.length };
}

/** Static prose a design ships (JSX text + prose strings in its data arrays), minus the owner's words
 *  and minus fallbacks of live slots. Used to rank (mockup-heavy designs lose) and to ledger what the
 *  owner still has to replace before launch. */
const ENT = { '&apos;': "'", '&#39;': "'", '&quot;': '"', '&amp;': '&', '&lt;': '<', '&gt;': '>', '&nbsp;': ' ' };
/** Text reduced to letters and digits (markup, quotes, punctuation and spacing never decide a match). */
export const flatText = (s) => String(s || '').replace(/&[#\w]+;/g, (m) => ENT[m] || ' ').replace(/<[^>]*>/g, '').normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');

/**
 * How much of the owner's content a hand-written (AI) component really holds: every text unit, link
 * target, image and bullet is looked up in its source. `invented` = words on it the owner never wrote.
 */
export function literalFit(root, dirRel, orig, dynamic = []) {
  const dir = path.join(root, dirRel);
  const code = fs.readdirSync(dir).filter((f) => /\.(tsx|jsx|ts|js)$/.test(f)).map((f) => fs.readFileSync(path.join(dir, f), 'utf8')).join('\n');
  const hay = flatText(code);
  const dynKey = new Map(dynamic.map((d) => [d.src, d.key]));
  const lit = (src) => { try { const v = JSON.parse(src); return typeof v === 'string' ? v : null; } catch { return null; } };
  const has = (v) => code.includes(JSON.stringify(v)) || code.includes(`'${v}'`) || code.includes('`' + v + '`');
  const carried = [], dropped = [];
  for (const u of orig.units) {
    let ok = u.dynamic ? new RegExp(`content\\??\\.${dynKey.get(u.src)}\\b`).test(code) : !flatText(u.text) || hay.includes(flatText(u.text));
    let text = u.text;
    const href = u.role === 'action' && u.href ? lit(u.href) : null;
    if (ok && href && !has(href)) { ok = false; text += ` (link ${href})`; }
    (ok ? carried : dropped).push({ role: u.role, text });
  }
  for (const im of orig.images) {
    const src = lit(im.src);
    if (src) (has(src) ? carried : dropped).push({ role: 'image', text: src });
  }
  for (const l of orig.lists) for (const it of l.items) for (const b of it.bullets || []) (hay.includes(flatText(b)) ? carried : dropped).push({ role: 'item', text: b });
  const own = orig.units.map((u) => flatText(u.text)).concat(orig.lists.flatMap((l) => l.items.flatMap((it) => (it.bullets || []).map(flatText)))).filter(Boolean);
  const invented = demoTexts(root, dirRel, []).map((e) => e.text).filter((t) => !own.some((o) => o.includes(flatText(t))));
  return { carried, dropped, invented: [...new Set(invented)], of: carried.length + dropped.length };
}

/**
 * Every word a staged design still shows of its own — literal text outside the content slots, and the rows of an
 * illustration drawn from the design's own data array (a fake customer table, a demo chat) — is marked
 * `data-dh-demo` on its element: dashed in the preview like any demo copy, never passed off as the owner's.
 * Keep removes the marks (the words themselves go to the demo-copy ledger).
 */
export function markDemo(file, code) {
  let ast;
  try { ast = parse(file, code); } catch { return code; }
  const hostOf = new Map();                                        // element start → opening element
  const literalArrays = new Set();
  walk(ast, (n) => {
    if (n.type === 'VariableDeclarator' && n.id.type === 'Identifier') {
      let init = n.init;
      while (init && /^TS(As|Satisfies)Expression$/.test(init.type)) init = init.expression;
      if (init && init.type === 'ArrayExpression' && init.elements.length && init.elements.every((e) => e && e.type === 'ObjectExpression')) literalArrays.add(n.id.name);
    }
    return true;
  });
  const mark = (el) => { if (el && /^[a-z][a-z0-9]*$/.test(jsxName(el.openingElement.name)) && !/^(svg|path|title|option|script|style)$/.test(jsxName(el.openingElement.name)) && !attr(el, 'data-dh-demo')) hostOf.set(el.start, el.openingElement); };
  // words inside a component (`<Button><Link>Get Started</Link></Button>`) have no plain element of their own: a
  // marked span wraps them (Keep unwraps it)
  const wraps = [];
  const markText = (n, el) => {
    if (!el || !/^[a-z]/.test(jsxName(el.openingElement.name))) { wraps.push(n); return; }
    mark(el);
  };
  // three letters or digits: "Get Started", but also a demo player's "0:45"
  const words = (t) => (String(t).match(/[\p{L}\p{N}]/gu) || []).length >= 3;
  const visit = (n, stack, inFallback, mapParam) => {
    if (!n || typeof n.type !== 'string') return;
    if (n.type === 'LogicalExpression' && n.operator === '??') { visit(n.left, stack, inFallback, mapParam); visit(n.right, stack, true, mapParam); return; }
    if (n.type === 'JSXAttribute') return;
    if (n.type === 'JSXElement') {
      if (attr(n, 'data-dh-demo')) return;                         // already a dashed slot fallback
      stack = stack.concat([n]);
    }
    if (n.type === 'JSXText' && !inFallback && words(n.value)) markText(n, stack[stack.length - 1]);
    if (n.type === 'JSXExpressionContainer' && mapParam && !inFallback) {
      let hit = false;
      walk(n.expression, (m) => { if (m.type === 'MemberExpression' && m.object.type === 'Identifier' && m.object.name === mapParam) hit = true; return !hit; });
      if (hit) mark(stack[stack.length - 1]);
    }
    if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression' && !n.callee.computed && n.callee.property.name === 'map'
      && n.callee.object.type === 'Identifier' && literalArrays.has(n.callee.object.name)) {
      const cb = n.arguments[0];
      const param = cb && cb.params && cb.params[0] && cb.params[0].type === 'Identifier' ? cb.params[0].name : null;
      if (cb) visit(cb.body, stack, inFallback, param || mapParam);
      return;
    }
    for (const k of Object.keys(n)) {
      if (k === 'loc' || k === 'start' || k === 'end' || k === 'extra' || /Comments$/.test(k)) continue;
      const v = n[k];
      if (Array.isArray(v)) for (const c of v) visit(c, stack, inFallback, mapParam);
      else if (v && typeof v.type === 'string') visit(v, stack, inFallback, mapParam);
    }
  };
  visit(ast.program, [], false, null);
  if (!hostOf.size && !wraps.length) return code;
  const edits = [...hostOf.values()].map((o) => ({ start: o.name.end, end: o.name.end, text: ' data-dh-demo=""' }));
  for (const n of wraps) {
    const a = n.start + (n.value.length - n.value.trimStart().length), b = n.end - (n.value.length - n.value.trimEnd().length);
    edits.push({ start: a, end: b, text: `<span data-dh-demo="" data-dh-wrap="">${code.slice(a, b)}</span>` });
  }
  edits.sort((x, y) => y.start - x.start);
  let out = code;
  for (const e of edits) out = out.slice(0, e.start) + e.text + out.slice(e.end);
  try { parse(file, out); } catch { return code; }
  return out;
}

/** Keep: the preview's demo marks go — wrapped words back to plain text, marked elements lose the attribute. */
export function unmarkDemo(code) {
  return code.replace(/<span data-dh-demo="" data-dh-wrap="">([^<{}]*)<\/span>/g, '$1').replace(/ data-dh-demo=""(?=[\s>/])/g, '');
}

const PRICE = /(^|\s)[$€£¥]\s?\d|\d\s?[$€£¥](\s|\/|$)|\d\s?(EUR|USD|GBP)\b/;

/**
 * The design's words still on the page. `ledger: true` (compose/keep, feeding demo-copy.json) also records a price
 * (`$19 / mo` has under three letters) and a dead `href="#"` link (F13); fit checks call it without, so counts do not move.
 */
export function demoTexts(root, dirRel, ownerTexts = [], { ledger = false } = {}) {
  const brand = brandName(root);   // the owner's own name is never demo copy
  const own = new Set(ownerTexts.concat(brand ? [brand, `© ${brand}`] : []).map((t) => String(t).replace(/\s+/g, ' ').trim().toLowerCase()));
  const out = [];
  const dir = path.join(root, dirRel);
  if (!fs.existsSync(dir)) return out;
  for (const f of fs.readdirSync(dir)) {
    if (!/\.(tsx|jsx)$/.test(f)) continue;
    const code = fs.readFileSync(path.join(dir, f), 'utf8');
    let ast;
    try { ast = parse(f, code); } catch { continue; }
    const push = (t, force = false) => {
      const x = String(t).replace(/\s+/g, ' ').trim();
      if (own.has(x.toLowerCase()) || (!force && (x.match(/\p{L}/gu) || []).length < 3)) return;
      if (x.split(/\s+/).every((t) => /^[a-z0-9:/[\]._%!*&>()-]+$/.test(t)) && /(^|\s)[a-z0-9:]+-[\w./-]+/.test(x)) return;   // a class list
      if (/^(https?:|\/|#|mailto:|tel:)/.test(x)) return;
      out.push({ file: path.posix.join(dirRel, f), text: x.slice(0, 120) });
    };
    walk(ast, (n, parent) => {
      if (n.type === 'LogicalExpression' && n.operator === '??') return false;          // a slot fallback
      if (n.type === 'JSXAttribute') {
        if (ledger && jsxName(n.name) === 'href' && n.value && n.value.type === 'StringLiteral' && /^#?$/.test(n.value.value.trim())) {
          out.push({ file: path.posix.join(dirRel, f), text: `href="${n.value.value}"`, kind: 'dead-link' });
        }
        return false;
      }
      if (n.type === 'ImportDeclaration' || n.type === 'TSTypeAnnotation') return false;
      if (n.type === 'JSXText') push(n.value, ledger && PRICE.test(n.value));
      if (n.type === 'StringLiteral' && parent && (parent.type === 'ObjectProperty' && parent.value === n || parent.type === 'ArrayExpression')) {
        if (/\s/.test(n.value) || /^[A-Z][a-z]+/.test(n.value) || (ledger && PRICE.test(n.value))) push(n.value, ledger && PRICE.test(n.value));
      }
      return true;
    });
  }
  return out;
}

export function recordDemoCopy(root, entries) {
  const p = path.join(root, '.deckhand', 'demo-copy.json');
  let doc = { entries: [] };
  try { doc = JSON.parse(fs.readFileSync(p, 'utf8')); } catch { /* new */ }
  const key = (e) => e.file + '\u0000' + e.text;
  const seen = new Set(doc.entries.map(key));
  for (const e of entries) if (!seen.has(key(e))) { doc.entries.push(e); seen.add(key(e)); }
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(doc, null, 1));
  return doc.entries.length;
}

const NOTICE_FILE = 'THIRD_PARTY_NOTICES.md';

function recordNotice(root, v) {
  const p = path.join(root, NOTICE_FILE);
  const regs = JSON.parse(fs.readFileSync(path.join(SKILL_DIR, 'data', 'registries.json'), 'utf8')).registries;
  const reg = regs.find((r) => r.id === v.r) || {};
  let text = fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : '# Third-party notices\n\nComponents adapted from open-source registries (kept via deckhand try-on).\n';
  const line = `- \`${v.finalDir || v.dir}\` — ${v.t} · ${v.r}/${v.n} · ${v.lic} · ${v.sourceUrl}${reg.copyright ? ' · ' + reg.copyright : ''}`;
  if (!text.includes(v.sourceUrl)) text = text.replace(/\s*$/, '\n') + line + '\n';
  if (reg.license === 'MIT' && !text.includes('Permission is hereby granted')) {
    text += '\n## MIT License (applies to the components above unless noted)\n\nPermission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:\n\nThe above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.\n\nTHE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.\n';
  }
  fs.writeFileSync(p, text);
}

export function keep(rootIn, id, idx) {
  const root = path.resolve(rootIn);
  const prof = detectProject(root);
  const s = loadSession(root, id);
  if (s.state !== 'open') throw new TryonError('SESSION_CLOSED', `session ${id} is ${s.state}`);
  const i = Number(idx ?? s.shown);
  if (i === 0) return discard(root, id, { reason: 'kept original' });
  const v = s.variants.find((x) => x.idx === i);
  if (!v) throw new TryonError('NO_VARIANT', `session ${id} has no variant ${i}`);
  const abs = path.join(root, s.file);
  let code = fs.readFileSync(abs, 'utf8');
  const w = findWrapper(parse(s.file, code), id);
  if (!w) throw new TryonError('WRAPPER_MISSING', 'the variant wrapper is gone from ' + s.file);
  const chosen = variantChildren(w).find((c) => Number(attr(c, 'data-dh-variant').value.value) === i);
  let inner = innerSrc(code, chosen);
  // graduate the folder
  const final = path.posix.join(prof.componentsDir, s.kind === 'block' ? 'sections' : 'ui-kit', v.slug);
  const shared = referencedByOtherOpen(root, v.dir, id);
  fs.mkdirSync(path.dirname(path.join(root, final)), { recursive: true });
  fs.rmSync(path.join(root, final), { recursive: true, force: true });
  if (shared) fs.cpSync(path.join(root, v.dir), path.join(root, final), { recursive: true });
  else fs.renameSync(path.join(root, v.dir), path.join(root, final));
  const entryFinal = path.posix.join(final, path.posix.basename(v.entry));
  const newSpec = specFor(prof, entryFinal) || './' + entryFinal;
  // a clean local name for the kept component
  const cleanLocal = uniqueName((v.generated ? pascal(s.slot) + 'AiDraft' : pascal(v.n)).slice(0, 48), identifiers(code.replace(new RegExp(`\\b${v.local}\\b`, 'g'), '')));
  inner = inner.replace(new RegExp(`\\b${v.local}\\b`, 'g'), cleanLocal);
  code = code.slice(0, w.start) + inner + code.slice(w.end);
  code = removeMarkedImports(code, id, v.local, newSpec).replace(new RegExp(`\\b${v.local}\\b`, 'g'), cleanLocal);
  parse(s.file, code);
  fs.writeFileSync(abs, code);
  // strip the staging header note, keep attribution
  const eAbs = path.join(root, entryFinal);
  for (const f of fs.readdirSync(path.join(root, final))) {
    const p = path.join(root, final, f);
    if (/\.(tsx|ts|jsx|js)$/.test(f)) fs.writeFileSync(p, fs.readFileSync(p, 'utf8').replace(' · staged by deckhand try-on */', ' */'));
  }
  const baked = s.kind === 'block' ? bake(root, s.file, cleanLocal, { ...v, entry: entryFinal }) : { baked: 0 };
  void eAbs;
  // the preview's demo marks go (the words stay, and the ledger below lists them)
  for (const f of fs.readdirSync(path.join(root, final))) {
    if (!/\.(tsx|jsx)$/.test(f)) continue;
    const p = path.join(root, final, f);
    const code = fs.readFileSync(p, 'utf8');
    const out = unmarkDemo(code);
    if (out !== code) { try { parse(f, out); fs.writeFileSync(p, out); } catch { /* keep the marked file rather than a broken one */ } }
  }
  // losers
  for (const o of s.variants) {
    if (o.idx === i) continue;
    if (!referencedByOtherOpen(root, o.dir, id)) fs.rmSync(path.join(root, o.dir), { recursive: true, force: true });
    if (o.css) removeCss(prof, /dh:css ([^ ]+) \*\//.exec(o.css)[1]);
  }
  const stageRoot = path.join(root, prof.componentsDir, 'dh-tryon');
  if (fs.existsSync(stageRoot) && !fs.readdirSync(stageRoot).length) fs.rmdirSync(stageRoot);
  v.finalDir = final;
  if (!v.generated) recordNotice(root, v);             // AI-written code is the owner's: provenance lives in its header
  let leftovers = demoTexts(root, final, v.ownerTexts || [], { ledger: true });
  if (v.generated) {
    const own = (v.ownerTexts || []).map(flatText);
    leftovers = leftovers.filter((e) => !own.some((o) => o.includes(flatText(e.text)))).map((e) => ({ ...e, ai: true }));
  }
  if (leftovers.length) recordDemoCopy(root, leftovers);
  s.state = 'kept';
  s.chosen = i;
  s.keptAt = now();
  s.final = { dir: final, entry: entryFinal, spec: newSpec, local: cleanLocal, baked };
  saveSession(root, s);
  return { ok: true, id, kept: v.t, file: s.file, component: entryFinal, local: cleanLocal, baked, fit: v.fit, notice: NOTICE_FILE,
    generated: !!v.generated,
    demo_copy_to_replace: leftovers.map((e) => e.text).slice(0, 20),
    next: v.generated ? (leftovers.length ? 'the AI wrote the words listed above — the owner confirms or rewrites them (dh rebrand check warns until then)' : null)
      : leftovers.length ? 'replace or delete the design\'s demo copy listed above (dh rebrand check blocks until then)' : null };
}

export function discard(rootIn, id, { reason } = {}) {
  const root = path.resolve(rootIn);
  const prof = detectProject(root);
  const s = loadSession(root, id);
  if (s.state !== 'open') throw new TryonError('SESSION_CLOSED', `session ${id} is ${s.state}`);
  const abs = path.join(root, s.file);
  const cur = fs.readFileSync(abs);
  let mode;
  if (sha(cur) === s.shaAfter) {
    fs.writeFileSync(abs, fs.readFileSync(path.join(root, s.backup)));
    mode = 'byte-exact';
  } else {
    let code = cur.toString('utf8');
    const w = findWrapper(parse(s.file, code), id);
    if (w) {
      const orig = variantChildren(w).find((c) => Number(attr(c, 'data-dh-variant').value.value) === 0);
      code = code.slice(0, w.start) + innerSrc(code, orig) + code.slice(w.end);
    }
    code = removeMarkedImports(code, id, null);
    parse(s.file, code);
    fs.writeFileSync(abs, code);
    mode = 'surgical (file changed since the try)';
  }
  for (const v of s.variants) {
    if (!referencedByOtherOpen(root, v.dir, id)) fs.rmSync(path.join(root, v.dir), { recursive: true, force: true });
    if (v.css) removeCss(prof, /dh:css ([^ ]+) \*\//.exec(v.css)[1]);
  }
  const stageRoot = path.join(root, prof.componentsDir, 'dh-tryon');
  const swept = sweepStage(root, stageRoot, id);
  if (fs.existsSync(stageRoot) && !fs.readdirSync(stageRoot).length) fs.rmdirSync(stageRoot);
  s.state = 'discarded';
  s.discardedAt = now();
  s.reason = reason || null;
  saveSession(root, s);
  // a package the try installed stays (package.json + lockfile): said, never silently left behind
  return { ok: true, id, restored: s.file, mode, ...(s.installed && s.installed.length ? { installedKept: s.installed } : {}), ...(swept.length ? { swept } : {}) };
}

/** Staging folders no other open session shows: left by a try that died mid-way. Removed; their names returned. */
function sweepStage(root, stageRoot, exceptId) {
  if (!fs.existsSync(stageRoot)) return [];
  const shown = new Set(listSessions(root).filter((o) => o.id !== exceptId && o.state === 'open').flatMap((o) => o.variants.map((v) => path.resolve(root, v.dir))));
  const out = [];
  for (const d of fs.readdirSync(stageRoot, { withFileTypes: true })) {
    if (!d.isDirectory() || shown.has(path.join(stageRoot, d.name))) continue;
    fs.rmSync(path.join(stageRoot, d.name), { recursive: true, force: true });
    out.push(d.name);
  }
  return out;
}

/** Where is this element, what could it be swapped with? (no writes) */
export function inspect(rootIn, { file, line, col, slot }) {
  const prof = detectProject(rootIn);
  const rel = String(file).replace(/\\/g, '/');
  const abs = path.resolve(prof.root, rel);
  if (!abs.startsWith(prof.root + path.sep)) throw new TryonError('OUTSIDE_PROJECT', rel + ' is outside the project');
  if (!fs.existsSync(abs)) throw new TryonError('NO_FILE', rel);
  const code = fs.readFileSync(abs, 'utf8');
  const el = findElementAt(parse(rel, code), code, Number(line), Number(col));
  if (!el) throw new TryonError('ELEMENT_NOT_FOUND', `${rel}:${line}:${col}`);
  const u = extractUnits(code, el, parse(rel, code));
  const r = slot ? rank(loadCatalog(), { slot, prof }) : { items: [], hidden: 0 };
  const lc = lineCol(code, el.end);
  return {
    file: rel, line: Number(line), col: Number(col), endLine: lc.line, tag: jsxName(el.openingElement.name),
    content: u.units.map((x) => ({ role: x.role, text: x.text.slice(0, 80), list: x.list })), images: u.images.length, lists: u.lists.length, dynamicLists: u.dynamicLists,
    project: { framework: prof.framework, base: prof.base, tailwind: prof.tailwind, tokens: prof.tokens.primary },
    ...(emptyUsage(el, u) ? { warning: emptyUsage(el, u) } : {}),
    candidates: r.items.length, hidden: r.hidden, top: r.items.slice(0, 8).map((x) => ({ id: x.id, t: x.t, missing: x.missing })),
  };
}

export { entryExport, slugOf };
