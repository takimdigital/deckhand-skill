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
import { offline, tempSite, read, locate } from './helpers.mjs';

offline();
// verdicts and added registries live beside the library: a private home for this file
const HOME = fs.mkdtempSync(path.join(os.tmpdir(), 'dh-fit-home-'));
process.env.DECKHAND_LIBRARY = path.join(HOME, 'library');

const { REFERENCE, REF_OF, referenceFor, makeSite, contextFor, checkItem, openSite, fitCheck, sampleOf, recordVerdicts, fitMarkdown, VERDICTS } = await import('../lib/fitcheck.mjs');
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
    assert.equal(referenceFor('chart'), null);
  } finally { site.close(); }
});

test('the site is what `dh scaffold` gives an owner: Next, Tailwind 4, tokens, Button, the radix-ui umbrella (or Base UI)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dh-fit-site-'));
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
  const chart = { ...libraryItem('a-chart', 'chart', { 'chart.tsx': 'export default function C() { return <div>chart</div>; }\n' }) };
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
  const fx = fs.mkdtempSync(path.join(os.tmpdir(), 'dh-fx-'));
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
