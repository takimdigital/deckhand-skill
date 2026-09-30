// The fit check: every design of a registry is staged the way a try stages it, against an owner section of its kind
// in a Deckhand scaffold site, and gets a verdict. Broken designs are never offered; refused ones come last.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { offline, tempSite, read, locate, scratch } from './helpers.mjs';

offline();
// verdicts and added registries live beside the library: a private home for this file
const HOME = scratch('dh-fit-home-');
process.env.DECKHAND_LIBRARY = path.join(HOME, 'library');

const { REFERENCE, REF_OF, permanentFetchFailure, referenceFor, makeSite, contextFor, checkItem, openSite, fitCheck, sampleOf, recordVerdicts, fitMarkdown, VERDICTS } = await import('../lib/fitcheck.mjs');
const { loadCatalog, rank, localChecksDir, kitOf } = await import('../lib/catalog.mjs');
const { detectProject } = await import('../lib/project.mjs');
const engine = await import('../lib/engine.mjs');
const { spdxOf } = await import('../lib/vet.mjs');
const require = createRequire(import.meta.url);
const { parse } = require('../lib/ast.cjs');
const CLI = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'cli.mjs');

const tailark = () => loadCatalog().filter((x) => x.r === 'tailark-oss');
const fixtureIds = ['tailark-oss/mist-hero-section-1@radix', 'tailark-oss/dusk-hero-section-1@radix', 'tailark-oss/mist-pricing-1@radix', 'tailark-oss/veil-call-to-action-1@radix'];

/** A personal-library design (offline): files as written, an entry, a slot. */
function libraryItem(name, slot, files) {
  const dir = path.join(process.env.DECKHAND_LIBRARY, 'components', name);
  fs.mkdirSync(dir, { recursive: true });
  for (const [f, text] of Object.entries(files)) fs.writeFileSync(path.join(dir, f), text);
  return { id: `mine/${name}@any`, r: 'mine', n: name, t: name, slot, kind: 'block', base: 'any', local: name, entry: Object.keys(files)[0], deps: [], lic: 'MIT' };
}

test('every owner section parses, is found where a click lands, and holds the owner\'s words', () => {
  const site = openSite();
  try {
    for (const slot of Object.keys(REFERENCE)) {
      parse(slot + '.tsx', REFERENCE[slot].code);
      const ctx = contextFor(site.prof('radix'), slot);
      assert.ok(ctx.origCount >= 1 || ctx.orig.inputs.length >= 1, slot + ' has content');
      assert.equal(ctx.slot, slot);
    }
    for (const [slot, ref] of Object.entries(REF_OF)) assert.ok(REFERENCE[ref], slot + ' -> ' + ref);
    assert.equal(referenceFor('signup'), 'login');
    assert.equal(referenceFor('no-such-kind'), null);
  } finally { site.close(); }
});

test('the site is what `dh scaffold` gives an owner: Next, Tailwind 4, tokens, Button, the radix-ui umbrella (or Base UI)', () => {
  const dir = scratch('dh-fit-site-');
  const p = makeSite(path.join(dir, 'r'));
  assert.equal(p.framework, 'next');
  assert.equal(p.tailwind, 4);
  assert.equal(p.base, 'radix');
  assert.ok(p.tokens.primary && p.tokens.radius);
  assert.ok(p.ui.button);
  assert.ok(fs.existsSync(path.join(p.root, 'node_modules/radix-ui/dist/dialog.mjs')), 'a design\'s @radix-ui/react-dialog resolves through the umbrella');
  const b = makeSite(path.join(dir, 'b'), { base: 'base-ui' });
  assert.equal(b.base, 'base-ui');
  assert.doesNotMatch(read(b.root, 'components/ui/button.tsx'), /radix-ui/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('verdicts: fits / partial / refused / broken / unreachable / unchecked, the staged files always removed', async () => {
  const broken = libraryItem('broken-hero', 'hero', { 'hero.tsx': 'import { Thing } from "@/lib/nowhere";\nexport default function H() { return <section><h1>Build faster</h1><Thing /></section>; }\n' });
  const chart = { ...libraryItem('a-chart', 'no-such-kind', { 'chart.tsx': 'export default function C() { return <div>chart</div>; }\n' }) };   // a kind with no owner section: still honestly unchecked
  const gone = { id: 'nope/none@radix', r: 'nope', n: 'none', t: 'None', slot: 'hero', kind: 'block', json: 'https://example.invalid/r/none.json' };
  const items = tailark().filter((x) => fixtureIds.includes(x.id)).concat([broken, chart, gone]);
  const res = await fitCheck({ id: 'mixed', items });
  const v = Object.fromEntries(res.results.map((r) => [r.id, r]));
  assert.equal(v['tailark-oss/mist-hero-section-1@radix'].verdict, 'fits');
  assert.equal(v['tailark-oss/mist-hero-section-1@radix'].carried, v['tailark-oss/mist-hero-section-1@radix'].of);
  assert.equal(v['tailark-oss/mist-pricing-1@radix'].verdict, 'refused');
  assert.match(v['tailark-oss/mist-pricing-1@radix'].why, /^POOR_FIT/);
  assert.equal(v['mine/broken-hero@any'].verdict, 'broken');
  assert.match(v['mine/broken-hero@any'].why, /UNRESOLVED_IMPORT.*@\/lib\/nowhere/);
  assert.equal(v['mine/a-chart@any'].verdict, 'unchecked');
  assert.equal(v['nope/none@radix'].verdict, 'unreachable');
  assert.ok(['partial', 'fits'].includes(v['tailark-oss/veil-call-to-action-1@radix'].verdict));
  assert.equal(Object.values(res.counts).reduce((a, b) => a + b, 0), items.length);
  assert.deepEqual(Object.keys(res.counts), VERDICTS);
  assert.deepEqual(res.results.map((r) => r.id), [...res.results.map((r) => r.id)].sort(), 'id order');
  // the same designs, the same verdicts (and the report is byte-identical)
  const again = await fitCheck({ id: 'mixed', items: [...items].reverse(), concurrency: 1 });
  assert.deepEqual(again.results, res.results);
  assert.equal(fitMarkdown(again), fitMarkdown(res));
  const md = fitMarkdown(res);
  assert.match(md, /^# Fit check — mixed\n/);
  assert.match(md, /## Broken \(1\)\n\n- `mine\/broken-hero@any` \(hero\): UNRESOLVED_IMPORT/);
  assert.match(md, /## By kind/);
});

test('a staged design is exactly one a try would offer: checkItem and open() agree', async () => {
  const site = openSite();
  const item = tailark().find((x) => x.id === 'tailark-oss/mist-hero-section-1@radix');
  const r = await checkItem(site, item);
  site.close();
  const dir = tempSite();
  const s = await engine.open(dir, { file: 'components/hero.tsx', ...locate(read(dir, 'components/hero.tsx'), '<section'), slot: 'hero', count: 1, only: item.id, install: false });
  assert.equal(r.verdict, 'fits');
  assert.equal(s.variants[1].id, item.id);
  engine.discard(dir, s.id);
});

test('a sample is deterministic and spread across kinds', () => {
  const all = tailark();
  const a = sampleOf(all, 6), b = sampleOf([...all].reverse(), 6);
  assert.deepEqual(a.map((x) => x.id), b.map((x) => x.id));
  assert.ok(new Set(a.map((x) => x.slot)).size >= 5, 'one of each kind before a second of any');
  assert.equal(sampleOf(all, 0).length, all.length);
});

test('recorded verdicts reach the catalog: broken is never offered (unless named), refused comes last', async () => {
  const prof = detectProject(tempSite());
  const heroes = rank(loadCatalog(), { slot: 'hero', prof, registry: 'tailark-oss' }).items;
  const [first, second] = heroes;
  const rec = recordVerdicts({ registry: 'tailark-oss', results: [
    { id: first.id, slot: 'hero', verdict: 'broken', why: 'UNRESOLVED_IMPORT: x' },
    { id: second.id, slot: 'hero', verdict: 'refused', why: 'POOR_FIT: carries 1/4' },
    { id: 'tailark-oss/zzz@radix', slot: 'hero', verdict: 'unreachable', why: 'FETCH_FAILED' },
  ] });
  try {
    assert.equal(path.dirname(rec.file), localChecksDir());
    const saved = JSON.parse(fs.readFileSync(rec.file, 'utf8'));
    assert.deepEqual(Object.keys(saved.verdicts), [first.id, second.id].sort(), 'a network failure is not a verdict');
    assert.match(saved.deckhand, /^\d+\.\d+\.\d+$/);
    const r = rank(loadCatalog(), { slot: 'hero', prof, registry: 'tailark-oss' });
    assert.ok(!r.items.some((x) => x.id === first.id));
    assert.equal(r.broken, 1);
    const kit = r.items.filter((x) => kitOf(x) === kitOf(second));
    assert.equal(kit.at(-1).id, second.id, 'refused: offered after every other design of its family');
    assert.ok(r.items.findIndex((x) => x.id === second.id) > heroes.findIndex((x) => x.id === second.id));
    assert.ok(rank(loadCatalog(), { slot: 'hero', prof, registry: 'tailark-oss', includeBroken: true }).items.some((x) => x.id === first.id));
    // a flag report's reproduce command still reaches a broken design
    const dir = tempSite();
    const s = await engine.open(dir, { file: 'components/hero.tsx', ...locate(read(dir, 'components/hero.tsx'), '<section'), slot: 'hero', count: 1, only: first.id, install: false });
    assert.equal(s.variants[1].id, first.id);
    engine.discard(dir, s.id);
  } finally { fs.rmSync(rec.file, { force: true }); }
});

test('CLI: `registry check` records the verdicts (and a report with --md); an unknown registry is refused', () => {
  const env = { ...process.env };
  const c = spawnSync(process.execPath, [CLI, 'registry', 'check', '--id', 'tailark-oss', '--sample', '3', '--md'], { encoding: 'utf8', env });
  const o = JSON.parse(c.stdout);
  assert.equal(o.ok, true, c.stdout);
  const row = o.registries[0];
  assert.equal(row.checked, 3);
  assert.ok(fs.existsSync(row.verdicts));
  assert.match(fs.readFileSync(row.report, 'utf8'), /^# Fit check — tailark-oss/);
  fs.rmSync(row.verdicts, { force: true });
  fs.rmSync(row.report, { force: true });
  const bad = spawnSync(process.execPath, [CLI, 'registry', 'check', '--id', 'nope'], { encoding: 'utf8', env });
  assert.equal(bad.status, 1);
  assert.equal(JSON.parse(bad.stdout).code, 'NO_SUCH_REGISTRY');
});

test('a licence read from the LICENSE file: permissive texts pass, a Commons Clause or copyleft never does', () => {
  const MIT = 'MIT License\n\nCopyright (c) 2025 x\n\nPermission is hereby granted, free of charge, to any person obtaining a copy of this software';
  assert.equal(spdxOf(MIT), 'MIT');
  assert.equal(spdxOf('"Commons Clause" License Condition v1.0 … the Software does not include the right to Sell … ' + MIT), 'OTHER');
  assert.equal(spdxOf('                                 Apache License\n                           Version 2.0, January 2004'), 'Apache-2.0');
  assert.equal(spdxOf('Redistribution and use in source and binary forms … Neither the name of the copyright holder'), 'BSD-3-Clause');
  assert.equal(spdxOf('Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted, provided that the above copyright notice and this permission notice appear in all copies.'), 'ISC');
  assert.equal(spdxOf('Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted.'), '0BSD');
  assert.equal(spdxOf('GNU AFFERO GENERAL PUBLIC LICENSE Version 3'), 'AGPL-3.0');
  assert.equal(spdxOf('This is free and unencumbered software released into the public domain.'), 'Unlicense');
  assert.equal(spdxOf('All rights reserved.'), 'OTHER');
});

/* ------------------------------------------------------------------ engine gaps the fit check found, pinned */

const { parameterize, extractUnits } = await import('../lib/transplant.mjs');
const { findElementAt } = require('../lib/ast.cjs');
const { carryPlanLinks, fitGate } = engine;

test('a design\'s "© {2026} Acme" line (a year in braces, or new Date()) is a copyright slot, not demo copy left on the page', () => {
  for (const y of ['{2026}', '{new Date().getFullYear()}']) {
    const code = `export default function F() { return (<footer><p>Links</p><span className="text-sm">© ${y} Tailark Mist, All rights reserved</span></footer>); }`;
    const p = parameterize('f.tsx', code, { kind: 'default' }, { stripChrome: true });
    assert.ok(p.slots.some((s) => s.role === 'copyright'), y);
    assert.match(p.code, /\{content\.copyright1 \?\?/);
  }
  // an expression that reads the design's own scope stays content it renders (never a slot)
  const dyn = parameterize('f.tsx', `export default function F({ year }) { return (<footer><span>© {year} Acme</span></footer>); }`, { kind: 'default' }, {});
  assert.ok(!dyn.slots.some((s) => s.role === 'copyright'));
});

test('a footer/navbar showing the plan\'s menu carries the owner\'s links that menu holds (the fit gate no longer refuses it)', () => {
  const links = { header: [{ label: 'Menu', href: '/menu' }, { label: 'Subscriptions', href: '/pricing' }], footerCols: [{ title: 'Maison Levain', links: [{ label: 'Legal notice', href: '/legal' }] }] };
  const code = `export function F() { return (<footer><p>Maison Levain</p><a href="/menu">Our menu</a><a href="/pricing">Subscriptions</a><a href="/legal/">Legal</a><a href="/careers">Careers</a></footer>); }`;
  const ast = parse('f.tsx', code);
  const i = code.indexOf('<footer');
  const orig = extractUnits(code, findElementAt(ast, code, 1, i + 1), ast);
  const b = { carried: [{ role: 'text', text: 'Maison Levain' }], dropped: orig.units.filter((u) => u.role === 'action').map((u) => ({ role: u.role, text: u.text })) };
  assert.equal(fitGate('block', 5, b) !== null, true, 'before: 1/5 carried, refused');
  carryPlanLinks(b, links, orig);
  assert.deepEqual(b.carried.map((c) => c.text), ['Maison Levain', 'Our menu', 'Subscriptions', 'Legal'], 'same route (a trailing slash aside) or same label');
  assert.deepEqual(b.dropped.map((d) => d.text), ['Careers'], 'a link the plan does not have is still dropped');
  assert.equal(fitGate('block', 5, b), null);
  assert.equal(carryPlanLinks({ carried: [], dropped: [{ role: 'action', text: 'Menu' }] }, null, orig).carried.length, 0, 'no plan, nothing assumed');
});

test('a Base UI button (`render={<Link>…</Link>}`, no children) carries the owner\'s action like its Radix twin', () => {
  const code = `export default function H() { return (<section><h1>Ship faster</h1><div><Button nativeButton={false} render={<Link href="#"><span className="text-nowrap">Start free</span></Link>} /><Button variant="ghost" nativeButton={false} render={<Link href="#">Watch demo</Link>} /></div></section>); }`;
  const p = parameterize('h.tsx', code, { kind: 'default' }, {});
  assert.deepEqual(p.slots.filter((s) => s.role === 'action').length, 2);
  assert.match(p.code, /render=\{\s*<Link href=\{content\.action\d+Href \?\? "#"\}><span className="text-nowrap">\{content\.action\d+ \?\?/);
  assert.match(p.code, /\{content\.action\d+Show !== false && \(<Button/, 'the whole button hides when the owner has no such action');
});

test('a shadcn block read raw: its page\'s one component is the entry, `from "cn"` is the project\'s utils, and a fetched primitive\'s own primitives are fetched too', async () => {
  const { fetchBundle, rawSource } = await import('../lib/materialize.mjs');
  const { keyOf } = await import('../lib/registry.mjs');
  const fx = scratch('dh-fx-');
  const put = (url, text) => fs.writeFileSync(path.join(fx, keyOf(url) + (text === 404 ? '.404' : '.txt')), text === 404 ? url : text);
  const GH = 'shadcn-ui/ui/main/apps/v4/registry/new-york-v4/blocks/login-01';
  put(`https://raw.githubusercontent.com/${GH}/page.tsx`, 'import { LoginForm } from "@/registry/new-york-v4/blocks/login-01/components/login-form"\nexport default function Page() { return <div className="min-h-svh"><LoginForm /></div> }\n');
  put(`https://raw.githubusercontent.com/${GH}/components/login-form.tsx`, 'import { cn } from "cn"\nimport { Field } from "@/registry/new-york-v4/ui/field"\nexport function LoginForm() { return <div className={cn("p-4")}><Field><h1>Login</h1></Field></div> }\n');
  for (const n of ['field', 'label', 'separator']) put(`https://ui.shadcn.com/r/styles/new-york-v4/${n}.json`, 404);
  put('https://raw.githubusercontent.com/shadcn-ui/ui/main/apps/v4/registry/new-york-v4/ui/field.tsx', 'import { cn } from "cn"\nimport { Label } from "@/registry/new-york-v4/ui/label"\nimport { Separator } from "@/registry/new-york-v4/ui/separator"\nexport function Field(p) { return <div className={cn("f")}><Label /><Separator />{p.children}</div> }\n');
  put('https://raw.githubusercontent.com/shadcn-ui/ui/main/apps/v4/registry/new-york-v4/ui/label.tsx', 'import * as LabelPrimitive from "@radix-ui/react-label"\nexport function Label(p) { return <LabelPrimitive.Root {...p} /> }\n');
  put('https://raw.githubusercontent.com/shadcn-ui/ui/main/apps/v4/registry/new-york-v4/ui/separator.tsx', 'export function Separator() { return <hr /> }\n');
  const was = process.env.DH_FIXTURES;
  process.env.DH_FIXTURES = fx;
  try {
    const prof = { ui: {}, base: 'radix', utilsExists: false, root: fx };
    const b = await fetchBundle(prof, { id: 'shadcn/login-01@radix', ghFiles: [`${GH}/page.tsx`, `${GH}/components/login-form.tsx`] });
    assert.equal(b.entry, 'apps/v4/registry/new-york-v4/blocks/login-01/components/login-form.tsx', 'the form, not the page that centres it');
    assert.deepEqual(b.files.map((f) => path.posix.basename(f.path)).sort(), ['field.tsx', 'label.tsx', 'login-form.tsx', 'page.tsx', 'separator.tsx']);
    assert.ok(!b.deps.includes('cn'), 'never an npm package named "cn"');
    assert.ok(b.deps.includes('@radix-ui/react-label'), 'a nested primitive\'s package is a dep');
    assert.ok(b.files.every((f) => !/from "cn"/.test(f.content)));
  } finally { process.env.DH_FIXTURES = was; }
  assert.equal(rawSource("import { cn } from 'cn'\nimport x from 'cnx'"), "import { cn } from '@/lib/utils'\nimport x from 'cnx'");
});

test('a primitive\'s part (CardHeader beside Card) stays in the design; a site header the block embeds is still stripped', () => {
  const code = `import { Card, CardHeader, CardTitle } from "./card"\nimport { HeroHeader } from "./header"\nexport default function L() { return (<section><HeroHeader /><Card><CardHeader><CardTitle>Login to your account</CardTitle></CardHeader></Card></section>); }`;
  const p = parameterize('l.tsx', code, { kind: 'default' }, { stripChrome: true });
  assert.deepEqual(p.removed, ['HeroHeader']);
  assert.match(p.code, /<CardHeader><CardTitle>\{content\.heading1 \?\?/);
});

test('footer columns titled by `group` (Tailark: `{ group, items: [{ title, href }] }`) take the plan\'s columns', async () => {
  const { fillLinks } = await import('../lib/sitelinks.mjs');
  const code = `const links = [{ group: 'Product', items: [{ title: 'Features', href: '#' }, { title: 'Solution', href: '#' }] }, { group: 'Company', items: [{ title: 'About', href: '#' }] }];\nexport default function F() { return <footer>{links.map((l) => <div key={l.group}>{l.group}{l.items.map((i) => <a key={i.title} href={i.href}>{i.title}</a>)}</div>)}</footer>; }`;
  const r = fillLinks('f.tsx', code, { header: [], footerCols: [{ title: 'Maison Levain', links: [{ label: 'Legal notice', href: '/legal' }] }], social: [], known: true }, 'footer');
  assert.deepEqual(r.filled, [{ array: 'links', kind: 'columns', count: 1 }]);
  assert.match(r.code, /\{ group: "Maison Levain", items: \[\{ href: "\/legal", title: "Legal notice" \}\] \}/);
  assert.doesNotMatch(r.code, /Features|Solution/);
});

test('the catalog build: --only rebuilds one registry from a snapshot and keeps every other item; radio groups are a slot', async () => {
  const { slotFromName } = await import('../lib/slots.mjs');
  assert.equal(slotFromName('radio-group-01'), 'radio-group');
  assert.equal(slotFromName('button-group'), null);
  const dir = scratch('dh-cb-');
  const out = path.join(dir, 'index.json');
  const keep = { id: 'tailark-oss/x@radix', r: 'tailark-oss', n: 'x', base: 'radix', slot: 'hero', kind: 'block' };
  fs.writeFileSync(out, JSON.stringify({ version: 2, count: 2, items: [keep, { id: 'blocks-so/gone@any', r: 'blocks-so', n: 'gone', slot: 'login' }] }));
  fs.writeFileSync(path.join(dir, 'blocks-so@base-nova.json'), JSON.stringify({ items: [
    { name: 'login-01', type: 'registry:block', files: [{ path: 'content/components/login/login-01.tsx' }] },
    { name: 'stats-02', type: 'registry:block', files: [] }, { name: 'notes', type: 'registry:lib' }] }));
  const r = spawnSync(process.execPath, [path.join(path.dirname(CLI), 'catalog-build.mjs'), '--only', 'blocks-so', '--snapshots', dir, '--out', out], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  const doc = JSON.parse(fs.readFileSync(out, 'utf8'));
  assert.deepEqual(doc.items.map((i) => i.id).sort(), ['blocks-so/login-01@any', 'blocks-so/stats-02@any', 'tailark-oss/x@radix']);
  assert.deepEqual(doc.items.find((i) => i.r === 'tailark-oss'), keep, 'another registry\'s item is kept as it was');
  assert.match(doc.items.find((i) => i.n === 'login-01').json, /^https:\/\/raw\.githubusercontent\.com\/ephraimduncan\/blocks\//);
});

test('a block importing another block\'s file, or its registry\'s own primitive, gets them from that registry', async () => {
  const { fetchBundle } = await import('../lib/materialize.mjs');
  const { keyOf } = await import('../lib/registry.mjs');
  const fx = scratch('dh-fx-');
  const put = (url, v) => fs.writeFileSync(path.join(fx, keyOf(url) + (v === 404 ? '.404' : '.txt')), v === 404 ? url : JSON.stringify(v));
  const R = 'https://raw.githubusercontent.com/o/blocks/main/public/r/';
  put(R + 'hero-03.json', { files: [{ path: 'src/registry/blocks/radix/hero-03/components/hero.tsx', content: 'import { Logo } from "@/registry/blocks/radix/navbar-04/components/logo"\nimport { Marquee } from "@/registry/bases/radix/ui/marquee"\nexport default function Hero() { return <section><Logo /><Marquee><h1>Hi</h1></Marquee></section> }\n' }] });
  put(R + 'navbar-04.json', { files: [{ path: 'src/registry/blocks/radix/navbar-04/components/navbar.tsx', content: 'export const N = 1\n' }, { path: 'src/registry/blocks/radix/navbar-04/components/logo.tsx', content: 'export function Logo() { return <svg /> }\n' }] });
  put('https://ui.shadcn.com/r/styles/new-york-v4/marquee.json', 404);
  fs.writeFileSync(path.join(fx, keyOf('https://raw.githubusercontent.com/shadcn-ui/ui/main/apps/v4/registry/new-york-v4/ui/marquee.tsx') + '.404'), 'x');
  put(R + 'marquee.json', { dependencies: ['motion'], files: [{ path: 'src/registry/bases/radix/ui/marquee.tsx', content: 'export function Marquee(p) { return <div>{p.children}</div> }\n' }] });
  const was = process.env.DH_FIXTURES;
  process.env.DH_FIXTURES = fx;
  try {
    const b = await fetchBundle({ ui: {}, base: 'radix', utilsExists: false, root: fx }, { id: 'o/hero-03@radix', json: R + 'hero-03.json' });
    assert.deepEqual(b.files.map((f) => path.posix.basename(f.path)).sort(), ['hero.tsx', 'logo.tsx', 'marquee.tsx'], 'only the file imported, not the whole other block');
    assert.ok(b.deps.includes('motion'));
  } finally { process.env.DH_FIXTURES = was; }
});

test('a login design whose form lives beside it (`<LoginForm />` from "./login-form") takes the owner\'s form there', () => {
  const code = `import { LoginForm } from "./login-form"\nimport { ContactForm } from "@/components/contact-form"\nexport default function L() { return (<section><h1>Welcome back</h1><LoginForm /></section>); }`;
  const p = parameterize('l.tsx', code, { kind: 'default' }, { forms: 'swap' });
  assert.deepEqual(p.formSwaps, ['form1']);
  assert.match(p.code, /\{content\.form1 \?\? \(<LoginForm \/>\)\}/);
  const q = parameterize('l.tsx', code.replace('<LoginForm />', '<ContactForm />'), { kind: 'default' }, { forms: 'swap' });
  assert.deepEqual(q.formSwaps, [], 'only a form component kept beside the design, never an import from elsewhere');
});

test('every slot the catalog ships has an owner section to be checked against (no kind is untestable)', async () => {
  const { BLOCK_SLOTS, UI_SLOTS, EFFECT_SLOTS } = await import('../lib/slots.mjs');
  const idx = JSON.parse(fs.readFileSync(new URL('../../data/components.index.json', import.meta.url), 'utf8'));
  const slots = new Set([...BLOCK_SLOTS, ...UI_SLOTS, ...EFFECT_SLOTS, ...idx.items.map((i) => i.slot)]);
  const missing = [...slots].filter((sl) => !referenceFor(sl));
  assert.deepEqual(missing, []);
});

test('the shipped verdicts cover every catalog design, and none is "unchecked"', () => {
  const idx = JSON.parse(fs.readFileSync(new URL('../../data/components.index.json', import.meta.url), 'utf8'));
  const dir = new URL('../../data/checks/', import.meta.url);
  const v = new Map();
  for (const f of fs.readdirSync(dir)) {
    if (!f.endsWith('.json')) continue;
    for (const [id, x] of Object.entries(JSON.parse(fs.readFileSync(new URL(f, dir), 'utf8')).verdicts)) v.set(id, x.v);
  }
  const none = idx.items.filter((i) => !v.has(i.id)).map((i) => i.id);
  const unchecked = [...v].filter(([, x]) => x === 'unchecked').map(([id]) => id);
  assert.deepEqual({ none: none.length, unchecked: unchecked.length }, { none: 0, unchecked: 0 }, none.concat(unchecked).slice(0, 20).join(', '));
});

test('a fetch that can never succeed (a dependency its registry does not ship, a 404) is broken; a network failure stays unreachable', () => {
  assert.equal(permanentFetchFailure('FETCH_FAILED smoothui/team-1@any — https://smoothui.dev/r/team-1.json: UNRESOLVED_REGISTRY_DEP @/lib/smoothui-data'), true);
  assert.equal(permanentFetchFailure('x: HTTP 404 https://raw.githubusercontent.com/a/b'), true);
  assert.equal(permanentFetchFailure('gh: UNRESOLVED_IMPORTS components/x/header.tsx | https://oss'), true);
  assert.equal(permanentFetchFailure('getaddrinfo ENOTFOUND example.invalid'), false);
  assert.equal(permanentFetchFailure(undefined), false);
});

test('a registry item served as JSON: a `from "cn"` alias in its files, or in a primitive it pulls, is the project\'s utils (never an npm package `cn`)', async () => {
  // found by a real-browser run: trying a contact design added a `cn` package to package.json, and Discard left it behind
  const { fetchBundle } = await import('../lib/materialize.mjs');
  const { keyOf } = await import('../lib/registry.mjs');
  const fx = scratch('dh-fx-');
  const putJson = (url, v) => fs.writeFileSync(path.join(fx, keyOf(url) + (v === 404 ? '.404' : '.txt')), v === 404 ? url : JSON.stringify(v));
  const URL = 'https://example.dev/r/contact-02.json';
  putJson(URL, { name: 'contact-02', dependencies: ['lucide-react', 'cn'], registryDependencies: ['card'], files: [
    { path: 'blocks/contact-02/contact.tsx', type: 'registry:block', content: 'import { cn } from "cn"\nimport { Card } from "@/components/ui/card"\nexport default function Contact() { return <Card className={cn("p-4")}><h1>Write to us</h1></Card> }\n' }] });
  putJson('https://ui.shadcn.com/r/styles/new-york-v4/card.json', { name: 'card', dependencies: ['cn'], files: [
    { path: 'registry/new-york-v4/ui/card.tsx', type: 'registry:ui', content: 'import { cn } from "cn"\nexport function Card(p: any) { return <div className={cn("rounded-xl border", p.className)} {...p} /> }\n' }] });
  const was = process.env.DH_FIXTURES;
  process.env.DH_FIXTURES = fx;
  try {
    const prof = { ui: {}, base: 'radix', utilsExists: false, root: fx };
    const b = await fetchBundle(prof, { id: 'x/contact-02@radix', json: URL, deps: ['cn'] });        // the catalog index lists it too (89 shadcn items)
    assert.ok(!b.deps.includes('cn'), 'never an npm package named "cn": ' + b.deps.join(','));
    assert.ok(b.files.length >= 2, 'the block and the primitive it pulled: ' + b.files.map((f) => f.path).join(','));
    assert.ok(b.files.every((f) => !/from ["']cn["']/.test(f.content)), 'every file imports the project\'s utils: ' + b.files.filter((f) => /from ["']cn["']/.test(f.content)).map((f) => f.path).join(','));
    assert.ok(b.files.some((f) => /from ["']@\/lib\/utils["']/.test(f.content)));
  } finally { process.env.DH_FIXTURES = was; }
});
