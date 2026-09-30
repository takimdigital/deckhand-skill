#!/usr/bin/env node
/**
 * compose.mjs — a page from licensed blocks + the plan's copy, no code generation.
 *
 *   node tryon/compose.mjs --project . --page app/page.tsx --sections navbar,hero,features,pricing,faq,cta,footer
 *                          [--copy .deckhand/copy.json] [--registry tailark-oss]
 *
 * copy.json (the one input a model writes, from the plan — words, never code):
 *   { "hero": { "heading": "…", "text": ["…"], "actions": [{ "label": "…", "href": "/order" }], "image": { "src": "/x.jpg", "alt": "…" } },
 *     "pricing": { "heading": "…", "items": [{ "title": "…", "price": "€9", "text": "…", "bullets": ["…"], "action": { "label": "…", "href": "…" } }] },
 *     "footer": { "text": ["…"], "columns": [{ "title": "…", "links": [{ "label": "…", "href": "/x" }] }], "social": ["https://instagram.com/…"] } }
 * Footer/navbar menus default to the plan (.deckhand/sitemap.json nav + page titles); social rows keep only
 * the networks in copy or brief.brand.social. A design's own form is hidden unless the section says
 * "form": true (the plan then wires it) — no newsletter box that posts nowhere.
 * Every section lands in components/sections/<slug>/, the page imports them in order; each is then
 * swappable with try-on. Copy the design has no room for is reported, never silently dropped.
 */
import fs from 'node:fs';
import path from 'node:path';
import { detectProject, specFor } from './lib/project.mjs';
import { loadCatalog, rank, kitOf } from './lib/catalog.mjs';
import { fetchBundle, writeBundle, pascal, slugOf } from './lib/materialize.mjs';
import { parameterize, bind, contentProp } from './lib/transplant.mjs';
import { ensureTokens, bake, PLACEHOLDER, logoLocalsFor, install, brandName, ensurePlaceholder, demoTexts, recordDemoCopy } from './lib/engine.mjs';
import { contentCount } from './lib/transplant.mjs';
import { siteLinks, fillLinks, linkTexts, FORM_SLOTS } from './lib/sitelinks.mjs';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
const { parse, walk, jsxName } = createRequire(import.meta.url)('./lib/ast.cjs');

const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf('--' + k); return i >= 0 ? args[i + 1] : d; };
const root = path.resolve(opt('project', '.'));
const page = opt('page', 'app/page.tsx');
let sections = String(opt('sections', 'navbar,hero,features,pricing,faq,cta,footer')).split(',').map((s) => s.trim()).filter(Boolean);
// an inner page gets no navbar/footer unless its section list names them (or the layout holds them): --chrome yes adds both
if (opt('chrome', 'no') === 'yes') {
  if (!sections.includes('navbar')) sections = ['navbar', ...sections];
  if (!sections.includes('footer')) sections = [...sections, 'footer'];
}
const registry = opt('registry', null);
const out = (o, c = 0) => { process.stdout.write(JSON.stringify(o) + '\n'); process.exit(c); };
let copy = {};
try { copy = opt('copy') ? JSON.parse(fs.readFileSync(path.resolve(root, opt('copy')), 'utf8')) : {}; }
catch (e) { out({ ok: false, code: 'BAD_COPY', message: `${opt('copy')}: ${e.message} (fix the JSON, then compose again)` }, 1); }

const esc = (s) => (/[{}<>]/.test(String(s)) ? `{${JSON.stringify(String(s))}}` : String(s));
const unit = (role, text, href) => ({ role, text: String(text), src: esc(text), href: href ? JSON.stringify(href) : null, list: null });

/** copy.json section -> the same shape extractUnits() returns for a clicked element. */
function origFromCopy(c = {}) {
  const units = [];
  if (c.eyebrow) units.push(unit('text', c.eyebrow));
  if (c.heading) units.push(unit('heading', c.heading));
  for (const t of [].concat(c.text || [])) units.push(unit('text', t));
  for (const a of [].concat(c.actions || [])) units.push(unit('action', a.label, a.href));
  const images = c.image ? [{ src: JSON.stringify(c.image.src), alt: JSON.stringify(c.image.alt || '') }] : [];
  const lists = [];
  if (Array.isArray(c.items) && c.items.length) {
    lists.push({ items: c.items.map((it) => {
      const us = [];
      if (it.title) us.push(unit('heading', it.title));
      if (it.price) us.push(unit('price', it.price));
      for (const t of [].concat(it.text || [])) us.push(unit('text', t));
      if (it.action) us.push(unit('action', it.action.label, it.action.href));
      return { units: us.map((u) => ({ ...u, list: 0 })), images: it.image ? [{ src: JSON.stringify(it.image.src), alt: JSON.stringify(it.image.alt || '') }] : [], bullets: it.bullets || [] };
    }) });
    lists[0].items.forEach((it, i) => it.units.forEach((u) => units.push({ ...u, item: i })));
  }
  return { units, images, inputs: [], lists, dynamicLists: 0 };
}

// A section folder holds ONE page's words (they are baked in), so a second page gets its own <slug>-2; re-composing the same page reuses its folders.
// Candidates stage in <sections>/.dh-stage-N (the same depth as the final folder, so relative imports hold); the winner
// then moves to <sections>/<slug>, or <slug>-2… when that folder exists: another page or a kept try-on may use it,
// and the owner may have edited it. Nothing already in <sections> is ever cleared.
const SECTIONS = (prof) => path.posix.join(prof.componentsDir, 'sections');
const LEDGER = () => path.join(root, '.deckhand', 'compose.json');
const readLedger = () => { try { return JSON.parse(fs.readFileSync(LEDGER(), 'utf8')); } catch { return {}; } };
/** A fingerprint of a staged folder: a re-compose of the SAME page reuses its own unedited folders instead of adding -2 copies. */
const folderSha = (abs) => {
  const h = crypto.createHash('sha256');
  const walkDir = (d) => { for (const e of fs.readdirSync(d, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const f = path.join(d, e.name); if (e.isDirectory()) walkDir(f); else { h.update(e.name); h.update(fs.readFileSync(f)); } } };
  if (fs.existsSync(abs)) walkDir(abs);
  return h.digest('hex');
};
function settle(prof, stage, cand) {
  let name = slugOf(cand), n = 1;
  // this page's own folder from an earlier compose, byte-identical to what compose left (nobody edited it): reuse its name
  const mine = (readLedger().pages || {})[page] || {};
  const prev = mine[cand.id];
  if (prev && prev.folder && fs.existsSync(path.join(root, prev.folder)) && folderSha(path.join(root, prev.folder)) === prev.sha) {
    fs.rmSync(path.join(root, prev.folder), { recursive: true, force: true });
    name = path.posix.basename(prev.folder);
    n = 0;
  }
  if (n) while (fs.existsSync(path.join(root, SECTIONS(prof), name))) name = `${slugOf(cand)}-${++n}`;
  const to = path.posix.join(SECTIONS(prof), name);
  try { fs.renameSync(path.join(root, stage.relDir), path.join(root, to)); }
  catch { fs.cpSync(path.join(root, stage.relDir), path.join(root, to), { recursive: true }); fs.rmSync(path.join(root, stage.relDir), { recursive: true, force: true }); }   // Windows: a watcher holds the folder
  const move = (p) => (typeof p === 'string' && p.startsWith(stage.relDir + '/') ? to + p.slice(stage.relDir.length) : p);
  const entry = move(stage.entry);
  return { ...stage, relDir: to, entry, spec: specFor(prof, entry) || './' + entry, files: (stage.files || []).map(move),
    logoFiles: Array.isArray(stage.logoFiles) ? stage.logoFiles.map(move) : stage.logoFiles };
}
const clearStages = (prof) => {
  const dir = path.join(root, SECTIONS(prof));
  if (fs.existsSync(dir)) for (const f of fs.readdirSync(dir)) if (f.startsWith('.dh-stage-')) fs.rmSync(path.join(dir, f), { recursive: true, force: true });
};

async function main() {
  const prof = detectProject(root);
  if (prof.tailwind === 4) ensureTokens(prof, {});
  const catalog = loadCatalog();
  const used = new Set();
  const placed = [];
  const report = [];
  const brand = brandName(root);
  const hasPublic = ensurePlaceholder(prof);
  const tries = Number(opt('tries', 8));
  let stageN = 0;
  clearStages(prof);
  for (const slot of sections) {
    const orig = origFromCopy(copy[slot]);
    const links = ['footer', 'navbar'].includes(slot) ? siteLinks(root, copy) : null;
    const of = Math.max(1, contentCount(orig));
    const ranked = rank(catalog, { slot, prof: detectProject(root), registry }).items;
    // stage up to `tries` candidates, keep the one that carries the most of the owner's content
    const staged = [];
    for (const cand of ranked.filter((c) => !placed.some((d) => d.cand.id === c.id)).slice(0, tries * 2)) {
      if (staged.length >= tries) break;
      let stage = null;
      try {
        const p0 = detectProject(root);
        const bundle = await fetchBundle(p0, cand);
        stage = writeBundle(p0, cand, bundle, { baseDir: SECTIONS(p0), dirName: `.dh-stage-${++stageN}` });
        if (stage.problems.length || !stage.export) { fs.rmSync(path.join(root, stage.relDir), { recursive: true, force: true }); continue; }
        const entryAbs = path.join(root, stage.entry);
        const entryCode = fs.readFileSync(entryAbs, 'utf8');
        const p = parameterize(stage.entry, entryCode, stage.export, { stripChrome: slot !== 'navbar', logoLocals: logoLocalsFor(stage, entryCode, slot),
          forms: FORM_SLOTS.has(slot) || (copy[slot] && copy[slot].form) ? 'keep' : 'hide' });
        const fl = fillLinks(stage.entry, p.code, links, slot);     // footer/navbar: the plan's routes
        p.code = fl.code;
        fs.writeFileSync(entryAbs, p.code);                 // demo text is measured on the slotted code
        const b = bind(orig, p, { placeholder: hasPublic ? PLACEHOLDER : null, brand });
        if (fl.filled.length) b.hidden.push(...fl.filled.map((f) => `${f.array}: ${f.kind} from your plan (${f.count})`));
        const demoVisual = demoTexts(root, stage.relDir, linkTexts(links)).length;
        // one design family across the page reads as one brand: a close call goes to the first section's kit
        const kin = placed.length && kitOf(placed[0].cand) === kitOf(cand) ? 0.1 : 0;
        const score = b.carried.length / of - 0.05 * b.demo.length - 0.04 * demoVisual - 0.02 * staged.length + kin;
        staged.push({ cand, stage, p, b, score });
        if (process.env.DH_DEBUG) console.error(slot, cand.id, 'carried', b.carried.length, '/', of, 'demo', b.demo.length, 'visual', demoVisual, 'score', score.toFixed(3));
      } catch (e) {
        if (stage && !staged.some((s) => s.stage.relDir === stage.relDir)) fs.rmSync(path.join(root, stage.relDir), { recursive: true, force: true });
        if (process.env.DH_DEBUG) console.error(slot, cand.id, 'FAILED', e.message);
      }
    }
    if (!staged.length) { report.push({ slot, ok: false, why: 'no candidate could be staged' }); continue; }
    // the owner's words are never silently dropped: a design that keeps all of them beats one that does not (ranked by carried/of)
    staged.sort((x, y) => (x.b.dropped.length > 0) - (y.b.dropped.length > 0) || y.score - x.score);
    const best = staged[0];
    for (const o of staged.slice(1)) fs.rmSync(path.join(root, o.stage.relDir), { recursive: true, force: true });
    best.stage = settle(prof, best.stage, best.cand);
    fs.writeFileSync(path.join(root, best.stage.entry), best.p.code);
    let local = pascal(best.cand.n).slice(0, 40);
    while (used.has(local)) local += '2';
    used.add(local);
    const done = { slot, cand: best.cand, stage: best.stage, prop: best.p.prop, local, usage: `<${local}${contentProp(best.p.prop, best.b.props)} />`, fit: best.b };
    placed.push(done);
    report.push({ slot, ok: true, component: done.stage.entry, from: done.cand.id, licence: done.cand.lic, compared: staged.length,
      carried: done.fit.carried.length, of, dropped: done.fit.dropped.map((d) => d.text), demo: done.fit.demo.map((d) => d.text), hidden: done.fit.hidden });
  }
  const imports = placed.map((d) => (d.stage.export.kind === 'default'
    ? `import ${d.local} from ${JSON.stringify(specFor(prof, d.stage.entry))}`
    : `import { ${d.stage.export.name} as ${d.local} } from ${JSON.stringify(specFor(prof, d.stage.entry))}`)).join('\n');
  clearStages(prof);
  const pageAbs = path.join(root, page);
  if (!placed.length) out({ ok: false, code: 'NOTHING_PLACED', message: `no section could be placed: ${page} is unchanged`, sections: report }, 1);
  // the first backup is the owner's own page: a later compose must not replace it with an earlier compose
  if (fs.existsSync(pageAbs) && !fs.existsSync(pageAbs + '.before-compose')) fs.copyFileSync(pageAbs, pageAbs + '.before-compose');
  fs.mkdirSync(path.dirname(pageAbs), { recursive: true });
  fs.writeFileSync(pageAbs, `${imports}\n\nexport default function Page() {\n  return (\n    <main>\n${placed.map((d) => '      ' + d.usage).join('\n')}\n    </main>\n  );\n}\n`);
  const ownerTexts = Object.values(copy).flatMap((c) => [c.eyebrow, c.heading, ...[].concat(c.text || []), ...[].concat(c.actions || []).map((a) => a.label),
    ...[].concat(c.items || []).flatMap((it) => [it.title, it.price, ...[].concat(it.text || []), it.action && it.action.label, ...(it.bullets || [])])])
    .concat(linkTexts(siteLinks(root, copy))).filter(Boolean);
  let demoLeft = [];
  for (const d of placed) {
    bake(root, page, d.local, { entry: d.stage.entry, prop: d.prop });
    const left = demoTexts(root, d.stage.relDir, ownerTexts, { ledger: true });
    demoLeft = demoLeft.concat(left);
    const r = report.find((x) => x.slot === d.slot);
    if (r) r.demo_copy = left.map((e) => e.text).slice(0, 12);
  }
  if (demoLeft.length) recordDemoCopy(root, demoLeft);
  // one <h1> per page (SEO/a11y): the first section's stays, later sections' become <h2> (classes keep the look)
  let h1Seen = false;
  for (const d of placed) {
    const f = path.join(root, d.stage.entry);
    const code = fs.readFileSync(f, 'utf8');
    const edits = [];
    walk(parse(d.stage.entry, code), (n) => {
      if (n.type === 'JSXElement' && jsxName(n.openingElement.name) === 'h1') {
        if (h1Seen) {
          edits.push([n.openingElement.name.start, n.openingElement.name.end]);
          if (n.closingElement) edits.push([n.closingElement.name.start, n.closingElement.name.end]);
        }
        h1Seen = true;
      }
      return true;
    });
    if (edits.length) fs.writeFileSync(f, edits.sort((a, b) => b[0] - a[0]).reduce((c, [a, b]) => c.slice(0, a) + 'h2' + c.slice(b), code));
  }
  // remember this page's folders (and their fingerprint after every edit above) so the next compose of it reuses them
  const led = readLedger();
  led.pages = led.pages || {};
  led.pages[page] = Object.fromEntries(placed.map((d) => [d.cand.id, { folder: d.stage.relDir, sha: folderSha(path.join(root, d.stage.relDir)) }]));
  fs.mkdirSync(path.dirname(LEDGER()), { recursive: true });
  fs.writeFileSync(LEDGER(), JSON.stringify(led, null, 1));
  const dropped = report.filter((r) => r.ok && r.dropped && r.dropped.length).flatMap((r) => r.dropped.map((text) => ({ slot: r.slot, text })));
  const deps = [...new Set(placed.flatMap((d) => d.stage.missingDeps))];
  let installed = null;
  if (deps.length && opt('install', 'yes') !== 'no') installed = install(detectProject(root), deps);
  const chromeMissing = page !== 'app/page.tsx' && !['navbar', 'footer'].every((s) => sections.includes(s));
  out({ ok: placed.length > 0, page, sections: report, dropped, deps,
    ...(dropped.length ? { pending: dropped.map((d) => ({ what: `the owner's text for ${d.slot} has no room in any design tried: \"${String(d.text).slice(0, 80)}\"`,
      how: 'add it as its own paragraph/section by hand in the page, or pick a section design with room (dh compose --sections … / try-on)', where: page })) } : {}),
    ...(chromeMissing ? { chrome: 'this page has no navbar/footer from compose: they come from app/layout.tsx, or pass --chrome yes' } : {}), installed, demo_copy_ledger: demoLeft.length ? '.deckhand/demo-copy.json' : null,
    next: dropped.length ? `PENDING: ${dropped.length} piece(s) of the owner's text were not placed (see dropped) — place them by hand or change the design, then dh compose again` : 'dh dev start; swap any section with try-on' + (installed && !installed.ok ? ` (install failed: ${installed.cmd})` : '') });
}
main().catch((e) => out({ ok: false, code: e.code || 'ERROR', message: String(e.message || e) }, 1));
