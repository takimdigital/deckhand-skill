// Field reports from an owner's Next 16 app (Turbopack), each replayed as a test:
//  1 footer swap → "Unexpected token '`', "`tel:${c.p"... is not valid JSON"
//  2 open → Discard → pick again → "ELEMENT_NOT_FOUND … blocks.tsx:64:7" (the page was older than the file)
//  3 a design needing @radix-ui/react-toggle broke the owner's page, and it stayed broken
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { tempSite, offline, read, locate } from './helpers.mjs';
import * as engine from '../lib/engine.mjs';
import { extractUnits, parameterize, bind, contentProp, contentCount } from '../lib/transplant.mjs';
import { radixUmbrella, writeBundle, reactAttrs } from '../lib/materialize.mjs';
import { fillLinks } from '../lib/sitelinks.mjs';
import { rank, loadCatalog } from '../lib/catalog.mjs';
import { detectProject } from '../lib/project.mjs';
import { requestDraft } from '../lib/draft.mjs';

const require = createRequire(import.meta.url);
const { parse, findElementAt } = require('../lib/ast.cjs');
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');

offline();

function unitsAt(code, needle) {
  const ast = parse('o.tsx', code);
  const i = code.indexOf(needle);
  const before = code.slice(0, i);
  return extractUnits(code, findElementAt(ast, code, before.split('\n').length, i - before.lastIndexOf('\n')), ast);
}

const OWNER_FOOTER = `import Link from "next/link";
const c = { phone: "+33 1 23 45 67 89", email: "hello@sparkleclean.fr", city: "Lyon" };
export function Footer() {
  return (
    <footer className="border-t px-6 py-10">
      <div className="grid md:grid-cols-3">
        <div>
          <p className="font-semibold">Sparkle Clean</p>
          <p className="mt-2">Commercial cleaning in {c.city}.</p>
        </div>
        <div>
          <p className="font-semibold">Contact</p>
          <a className="block" href={\`tel:\${c.phone}\`}>{c.phone}</a>
          <a className="block" href={\`mailto:\${c.email}\`}>{c.email}</a>
        </div>
        <div>
          <p className="font-semibold">Company</p>
          <Link className="block" href="/about">About</Link>
          <Link className="block" href="/quote">Get a quote</Link>
        </div>
      </div>
    </footer>
  );
}`;

const LINK_FOOTER = `import Link from 'next/link'
const links = [
  { title: 'Features', href: '#' },
  { title: 'Solution', href: '#' },
  { title: 'Customers', href: '#' },
  { title: 'Pricing', href: '#' },
]
export default function FooterSection() {
  return (
    <footer className="py-16">
      <div className="flex flex-wrap gap-6 text-sm">
        {links.map((link, index) => (
          <Link key={index} href={link.href} className="block"><span>{link.title}</span></Link>
        ))}
      </div>
    </footer>
  )
}`;

test('field 1: link hrefs that are template literals and {c.phone} labels travel as code, never through JSON', () => {
  const orig = unitsAt(OWNER_FOOTER, '<footer');
  const p = parameterize('c.tsx', LINK_FOOTER, { kind: 'default' }, { stripChrome: true });
  const b = bind(orig, p, {});                                   // threw "…is not valid JSON" before
  const usage = `<X${contentProp(p.prop, b.props)} />`;
  assert.match(usage, /"href": `tel:\$\{c\.phone\}`/);
  assert.match(usage, /"href": `mailto:\$\{c\.email\}`/);
  assert.match(usage, /"title": c\.phone\b/);                   // the value, not the text "{c.phone}"
  assert.doesNotMatch(usage, /"\{c\.phone\}"/);
  assert.match(usage, /"title": "About", "href": "\/about"/);
  // the owner's titled columns flatten into the design's one link list: every link is carried
  assert.ok(b.carried.length >= 4, `carried ${b.carried.length}/${contentCount(orig)}`);
  parse('u.tsx', `const c = { phone: "", email: "" }; const X = (p: any) => null; export const Y = () => ${usage};`);
});

test('field 1: a name bound inside the clicked element (a .map item) never leaks into the usage', () => {
  const OWNER = `const phones = getPhones();
export function Footer() {
  return (
    <footer className="py-10">
      <p>Call us any day</p>
      {phones.map((it) => (
        <a key={it.n} href={\`tel:\${it.n}\`}>{it.label}</a>
      ))}
    </footer>
  );
}`;
  const orig = unitsAt(OWNER, '<footer');
  assert.ok(orig.inner.has('it'));
  const p = parameterize('c.tsx', LINK_FOOTER, { kind: 'default' }, { stripChrome: true });
  const usage = `<X${contentProp(p.prop, bind(orig, p, {}).props)} />`;
  assert.doesNotMatch(usage, /\bit\./);                         // `it` does not exist where the usage is written
  parse('u.tsx', `const X = (p: any) => null; export const Y = () => ${usage};`);
});

test('field 3: with the radix-ui umbrella installed, @radix-ui/react-* imports use it (nothing to install)', () => {
  const dir = tempSite();
  const dist = path.join(dir, 'node_modules', 'radix-ui', 'dist');
  fs.mkdirSync(dist, { recursive: true });
  for (const n of ['index', 'internal', 'toggle', 'slot']) fs.writeFileSync(path.join(dist, n + '.mjs'), 'export {}\n');
  const prof = detectProject(dir);
  assert.deepEqual([...radixUmbrella(prof)].sort(), ['slot', 'toggle']);
  const bundle = {
    entry: 'blocks/content.tsx', external: {}, sourceUrl: 'https://example.test/c', deps: ['@radix-ui/react-toggle', '@radix-ui/react-accordion'],
    files: [{ path: 'blocks/content.tsx', content: `import * as TogglePrimitive from '@radix-ui/react-toggle'\nimport * as Acc from "@radix-ui/react-accordion"\nexport default function C() { return <TogglePrimitive.Root><Acc.Root /></TogglePrimitive.Root> }\n` }],
  };
  const st = writeBundle(prof, { r: 'tailark-oss', n: 'content-x', t: 'Content X' }, bundle);
  const code = read(dir, st.entry);
  assert.match(code, /from 'radix-ui\/toggle'/);
  assert.match(code, /from "@radix-ui\/react-accordion"/);      // not in the umbrella here: left as is
  assert.deepEqual(st.viaUmbrella, ['@radix-ui/react-toggle']);
  assert.ok(!st.deps.includes('@radix-ui/react-toggle'));
  assert.ok(st.missingDeps.includes('@radix-ui/react-accordion'));
});

/** A real, loadable node_modules for the import gate (stubs with no code are "unknown" and never count). */
function gateSite() {
  const dir = tempSite();
  const nm = path.join(dir, 'node_modules');
  const pkg = (name, files, extra = {}) => {
    fs.rmSync(path.join(nm, name), { recursive: true, force: true });
    fs.mkdirSync(path.join(nm, name), { recursive: true });
    fs.writeFileSync(path.join(nm, name, 'package.json'), JSON.stringify({ name, version: '1.0.0', type: 'module', ...extra }));
    for (const [f, c] of Object.entries(files)) { fs.mkdirSync(path.dirname(path.join(nm, name, f)), { recursive: true }); fs.writeFileSync(path.join(nm, name, f), c); }
  };
  pkg('icons', { 'index.js': 'export const ArrowRight = 1; export const Mail = 2;\n' }, { exports: { '.': './index.js' } });
  // an umbrella whose part re-exports a package nobody installed (pnpm/strict layouts, a partial install)
  pkg('umb', { 'dist/part.mjs': 'export * from "umb-part-impl";\n', 'dist/ok.mjs': 'export const Root = 1;\n' }, { exports: { './*': './dist/*.mjs' } });
  fs.mkdirSync(path.join(nm, 'stubonly'), { recursive: true });
  fs.writeFileSync(path.join(nm, 'stubonly', 'package.json'), JSON.stringify({ name: 'stubonly', version: '0.0.0' }));
  const stage = (name, code) => {
    fs.mkdirSync(path.join(dir, 'components/dh-tryon', name), { recursive: true });
    fs.writeFileSync(path.join(dir, 'components/dh-tryon', name, name + '.tsx'), code);
    return { id: 'x/' + name, slug: name, dir: 'components/dh-tryon/' + name };
  };
  return { dir, stage };
}

test('field 3: the import gate names what would break the build — missing export, namespace member, a package behind an umbrella, not installed', () => {
  const { dir, stage } = gateSite();
  const good = stage('good', `import { ArrowRight } from 'icons'\nimport * as P from 'umb/ok'\nimport Stub from 'stubonly'\nexport default () => <P.Root><ArrowRight /><Stub /></P.Root>\n`);
  const named = stage('named', `import { ArrowRight, Github } from 'icons'\nexport default () => <Github />\n`);
  const ns = stage('ns', `import * as I from 'icons'\nexport default () => <I.Twitter />\n`);
  const nsCall = stage('nscall', `import * as P from 'umb/ok'\nexport default () => P.Trigger()\n`);
  const behind = stage('behind', `import * as TogglePrimitive from 'umb/part'\nexport default () => <TogglePrimitive.Root />\n`);
  const absent = stage('absent', `import { motion } from 'no-such-pkg'\nexport default () => <motion.div />\n`);
  const g = engine.checkImports(dir, [good, named, ns, nsCall, behind, absent]);
  assert.equal(g.bad.has(good), false, g.bad.get(good));
  assert.equal(g.bad.get(named), 'icons has no Github');
  assert.equal(g.bad.get(ns), 'icons has no Twitter');
  assert.equal(g.bad.get(nsCall), 'umb/ok has no Trigger');
  assert.equal(g.bad.get(behind), 'umb/part needs umb-part-impl, which is not installed');
  assert.equal(g.bad.get(absent), 'no-such-pkg is not installed');
});

test('field 2: a stale stamp finds its element again by what it is; an unknown one says "reload"', async () => {
  const dir = tempSite();
  const src = read(dir, 'components/hero.tsx');
  const at = locate(src, '<section');
  const hint = { tag: 'section', text: 'Sourdough delivered warm to your door Maison Levain bakes every loaf' };
  // the page was rendered while a session had 4 import lines on top: its stamps are 4 lines ahead of the file
  const s = await engine.open(dir, { file: 'components/hero.tsx', line: at.line + 4, col: at.col + 2, slot: 'hero', count: 1, registry: 'tailark-oss', install: false, hint });
  assert.equal(s.line, at.line);
  engine.discard(dir, s.id);
  assert.equal(read(dir, 'components/hero.tsx'), src);
  // the stamp lands on the <h1> inside: not what was clicked (a section) — found again, never the wrong element
  const h1 = locate(src, '<h1');
  const s2 = await engine.open(dir, { file: 'components/hero.tsx', ...h1, slot: 'hero', count: 1, registry: 'tailark-oss', install: false, hint });
  assert.equal(s2.line, at.line);
  engine.discard(dir, s2.id);
  // nothing there, nothing like it: a clear "reload", nothing written
  await assert.rejects(engine.open(dir, { file: 'components/hero.tsx', line: 40, col: 3, slot: 'hero', count: 1, install: false, hint: { tag: 'section', text: 'A section that is gone now' } }),
    (e) => e.code === 'ELEMENT_NOT_FOUND' && e.reload === true && /reload/.test(e.message));
  assert.equal(read(dir, 'components/hero.tsx'), src);
  // fitsHint: sure mismatches only (another host tag, text that starts differently); an expression first = unknown
  const fx = `export const F = () => (<div><h2 className="uppercase">Get a quote</h2><p>{city} cleaning crews</p></div>);`;
  const fa = parse('f.tsx', fx);
  const h2 = findElementAt(fa, fx, 1, fx.indexOf('<h2') + 1);
  const pEl = findElementAt(fa, fx, 1, fx.indexOf('<p>') + 1);
  assert.equal(engine.fitsHint(h2, { tag: 'h2', text: 'GET A QUOTE' }), true);
  assert.equal(engine.fitsHint(h2, { tag: 'p', text: 'GET A QUOTE' }), false);
  assert.equal(engine.fitsHint(h2, { tag: 'h2', text: 'Other heading text' }), false);
  assert.equal(engine.fitsHint(pEl, { tag: 'p', text: 'Lyon cleaning crews' }), true);
  assert.equal(engine.fitsHint(h2, null), true);
  // <Link> is an <a> on the page, <Button> a <button>: a component is never a sure mismatch for a host tag
  const lx = `export const L = () => (<nav><Link href="/quote">Get a quote</Link><div>Other</div></nav>);`;
  const la = parse('l.tsx', lx);
  const link = findElementAt(la, lx, 1, lx.indexOf('<Link') + 1);
  assert.equal(engine.fitsHint(link, { tag: 'a', text: 'Get a quote' }), true);
  assert.equal(engine.fitsHint(findElementAt(la, lx, 1, lx.indexOf('<div>') + 1), { tag: 'Link', text: 'Other' }), false);
  assert.equal(engine.relocate(la, lx, { tag: 'a', text: 'Get a quote' }, 1).start, link.start);
  // relocate: nearest unambiguous match or nothing
  const code = `export const A = () => (<div>\n<section><h2>Get a quote</h2></section>\n<section><h2>Other</h2></section>\n</div>);`;
  const ast = parse('a.tsx', code);
  assert.equal(engine.relocate(ast, code, { tag: 'section', text: 'Get a quote' }, 9).start, code.indexOf('<section'));
  assert.equal(engine.relocate(ast, code, { tag: 'section', text: 'Nowhere' }, 2), null);
  const twin = `export const A = () => (<div>\n<p>Same text here</p>\n<p>Same text here</p>\n</div>);`;
  assert.equal(engine.relocate(parse('t.tsx', twin), twin, { tag: 'p', text: 'Same text here' }, 2).start, twin.indexOf('<p>'));
  assert.equal(engine.relocate(parse('t.tsx', twin), twin, { tag: 'p', text: 'Same text here' }, 2.5), null);   // equidistant: ambiguous
});

test('field 2: an AI draft asked from a stale page drafts the element that was clicked', () => {
  const dir = tempSite();
  const src = read(dir, 'components/hero.tsx');
  const at = locate(src, '<section');
  const h1 = locate(src, '<h1');
  const d = requestDraft(dir, { file: 'components/hero.tsx', ...h1, slot: 'hero', hint: { tag: 'section', text: 'Sourdough delivered warm to your door' } });
  assert.equal(d.file, 'components/hero.tsx');
  const saved = JSON.parse(read(dir, `.deckhand/tryon/drafts/${d.id}.json`));
  assert.equal(saved.request.line, at.line);
  assert.throws(() => requestDraft(dir, { file: 'components/hero.tsx', line: 40, col: 3, slot: 'hero', hint: { tag: 'section', text: 'Gone' } }),
    (e) => e.code === 'ELEMENT_NOT_FOUND' && e.reload === true);
});

test('buildError: a 500, or a build message on any status; a healthy page is not an error', () => {
  assert.equal(engine.buildError({ status: 200, text: '<html>fine</html>' }), null);
  assert.equal(engine.buildError({ status: 0, text: 'ECONNREFUSED' }), null);
  assert.match(engine.buildError({ status: 200, text: '<pre>Build Error Module not found: Can\'t resolve \'x\'</pre>' }), /Module not found/);
  assert.match(engine.buildError({ status: 500, text: '"message":"./components/dh-tryon/a/a.tsx:4:1\\nError: Export Github doesn\'t exist in target module"' }), /\.\/components\/dh-tryon\/a\/a\.tsx:4:1 Error: Export Github/);
  assert.equal(engine.buildError({ status: 500, text: 'oops' }), 'oops');
});

/**
 * A dev server stand-in: renders the hero file, lags one request behind every write (a file watcher does),
 * and fails to build while the file imports a variant listed in `breaks` (the error names that variant's folder,
 * or only the module it cannot load when `named` is false).
 */
function fakeDev(dir, { breaks = () => false, named = true } = {}) {
  let served = read(dir, 'components/hero.tsx');
  let seen = served;
  const server = http.createServer((req, res) => {
    const now = read(dir, 'components/hero.tsx');
    if (now !== seen) { seen = now; res.writeHead(200); res.end(`<html>${served.length}</html>`); return; }   // the stale compile
    served = now;
    const bad = [...served.matchAll(/from "[^"]*dh-tryon\/([\w-]+)\/[\w-]+" \/\/ dh-tryon:(\w+)/g)].find((m) => breaks(m[1]));
    if (bad) {
      res.writeHead(500);
      res.end(named ? `{"message":"./components/dh-tryon/${bad[1]}/x.tsx:5:1\\nModule not found: Can't resolve 'ghost-pkg'"}`
        : `{"message":"./node_modules/ghost-umb/dist/part.mjs:2:1\\nModule not found: Can't resolve 'ghost-impl'"}`);
      return;
    }
    const m = /data-dh-session="(\w+)"/.exec(served);
    res.writeHead(200);
    res.end(`<html><main>${m ? `<div data-dh-session="${m[1]}"></div>` : 'hero'}</main></html>`);
  });
  return new Promise((r) => server.listen(0, '127.0.0.1', () => r({ server, url: `http://127.0.0.1:${server.address().port}` })));
}

test('field 3: a variant that breaks the build is found once the dev server caught up, dropped, and the rest reopen', async () => {
  const dir = tempSite();
  const at = locate(read(dir, 'components/hero.tsx'), '<section');
  let victim = null;
  const { server, url } = await fakeDev(dir, { breaks: (slug) => (victim = victim || slug) === slug });
  try {
    const s = await engine.openVerified(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', count: 2, registry: 'tailark-oss', install: false },
      { url, page: '/', deadlineMs: 5000 });
    assert.equal(s.verified, true);
    assert.equal(s.dropped.length, 1);
    assert.ok(s.dropped[0].id.includes(victim.replace(/^tailark-oss-/, '')), `${s.dropped[0].id} ~ ${victim}`);
    assert.ok(!s.variants.some((v) => v.id === s.dropped[0].id));
    assert.match(read(dir, 'components/hero.tsx'), new RegExp(`data-dh-session="${s.id}"`));
    const first = fs.readdirSync(path.join(dir, '.deckhand/tryon/sessions')).map((f) => JSON.parse(read(dir, '.deckhand/tryon/sessions/' + f))).find((x) => x.id !== s.id);
    assert.equal(first.state, 'discarded');
    assert.equal(first.reason, 'build');
  } finally { server.close(); }
});

test('field 3: an error that points at no variant restores the file byte-exact and says so', async () => {
  const dir = tempSite();
  const before = fs.readFileSync(path.join(dir, 'components/hero.tsx'));
  const at = locate(before.toString(), '<section');
  const { server, url } = await fakeDev(dir, { breaks: () => true, named: false });
  try {
    await assert.rejects(engine.openVerified(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', count: 2, registry: 'tailark-oss', install: false },
      { url, page: '/', deadlineMs: 5000 }), (e) => e.code === 'BUILD_BROKE' && e.restored === true);
    assert.equal(sha(fs.readFileSync(path.join(dir, 'components/hero.tsx'))), sha(before));
    assert.ok(!fs.existsSync(path.join(dir, 'components/dh-tryon')));
  } finally { server.close(); }
});

test('culpritsOf: the variant folder in the trace, else the module it cannot load — never a framework stack frame', () => {
  const { dir, stage } = gateSite();
  const a = stage('va', `import * as T from 'umb/part'\nexport default () => <T.Root />\n`);
  const b = stage('vb', `import { ArrowRight } from 'icons'\nimport Link from 'next/link'\nexport default () => <ArrowRight />\n`);
  assert.deepEqual(engine.culpritsOf(dir, [a, b], 'Import traces: ./components/dh-tryon/vb/vb.tsx [Client Component]').map((v) => v.slug), ['vb']);
  assert.deepEqual(engine.culpritsOf(dir, [a, b], './node_modules/umb/dist/part.mjs:2:1 Module not found: Can\'t resolve \'umb-part-impl\'').map((v) => v.slug), ['va']);
  assert.deepEqual(engine.culpritsOf(dir, [a, b], 'at render (./node_modules/next/dist/server/render.js:10:5)'), []);
});

test('an unreachable dev server never blocks the swap: opened, marked unverified', async () => {
  const dir = tempSite();
  const at = locate(read(dir, 'components/hero.tsx'), '<section');
  const s = await engine.openVerified(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', count: 1, registry: 'tailark-oss', install: false },
    { url: 'http://127.0.0.1:9', page: '/', deadlineMs: 1000 });
  assert.equal(s.verified, false);
  assert.match(s.note, /did not answer/);
  engine.discard(dir, s.id);
});

// ---------------------------------------------------------------- the 2.3.0 real-browser test report (Next 16 labs)

test('report 1: a footer whose demo columns were emptied still renders the owner\'s columns (was HTTP 500 on links.map)', () => {
  const DESIGN = `const footerSections = [
  { title: "Product", links: [{ title: "Overview", href: "#" }, { title: "Pricing", href: "#" }] },
  { title: "Company", links: [{ title: "About us", href: "#" }, { title: "Careers", href: "#" }] },
];
export default function Footer() {
  return (<footer>{footerSections.map(({ title, links }) => (<div key={title}><h6>{title}</h6><ul>{links.map(({ title, href }) => (<li key={title}><a href={href}>{title}</a></li>))}</ul></div>))}<span>© Acme</span></footer>);
}`;
  const OWNER = `const cols = [
  { title: "Visit", links: [{ label: "Order", href: "/order" }] },
  { title: "Bakery", links: [{ label: "Our story", href: "/story" }] },
];
export function F() { return (<footer>{cols.map((c) => (<div key={c.title}><h4>{c.title}</h4><ul>{c.links.map((l) => (<li key={l.label}><a href={l.href}>{l.label}</a></li>))}</ul></div>))}</footer>); }`;
  const p = parameterize('f.jsx', DESIGN, { kind: 'default' }, { stripChrome: true });
  const fl = fillLinks('f.jsx', p.code, { header: [], footerCols: [], social: [], known: false }, 'footer');
  assert.equal(fl.filled[0].demoHidden, 2, 'no menu in the plan: the demo columns are emptied');
  const b = bind(unitsAt(OWNER, '<footer'), p, {});
  assert.ok(b.props.some(([k]) => k === 'list1'), 'the owner\'s columns go into the list');
  // run the list expression the way React would: every column's `links` must be an array
  const ast = parse('f.jsx', fl.code);
  let expr = null;
  require('../lib/ast.cjs').walk(ast, (n) => {
    if (!expr && n.type === 'CallExpression' && n.callee.type === 'MemberExpression' && n.callee.object.type === 'ConditionalExpression') { expr = n.callee.object; return false; }
    return true;
  });
  const list1 = [{ title: 'Visit' }, { title: 'Bakery' }];
  const rows = new Function('content', 'footerSections', `return (${fl.code.slice(expr.start, expr.end)});`)({ list1 }, []);
  assert.deepEqual(rows.map((r) => [r.title, r.links.map((l) => l.title)]), [['Visit', []], ['Bakery', []]]);
});

test('report 1: a try with no dev server known says the page was not checked', async () => {
  const dir = tempSite();
  const at = locate(read(dir, 'components/hero.tsx'), '<section');
  const s = await engine.openVerified(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', count: 1, registry: 'tailark-oss', install: false });
  assert.equal(s.verified, false);
  assert.match(s.note, /not checked.*--url/);
  engine.discard(dir, s.id);
});

test('report 1: when every design that fits broke the page, the error says so (not "no candidates")', async () => {
  const dir = tempSite();
  const hero = fs.readFileSync(path.join(dir, 'components/hero.tsx'));
  const at = locate(hero.toString(), '<section');
  const one = rank(loadCatalog(), { slot: 'hero', prof: detectProject(dir), registry: 'tailark-oss' }).items[0].id;
  const { server, url } = await fakeDev(dir, { breaks: () => true });
  try {
    await assert.rejects(engine.openVerified(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', count: 1, only: one, install: false }, { url, page: '/', deadlineMs: 5000 }),
      (e) => e.code === 'BUILD_BROKE' && e.restored === true && e.dropped.length === 1 && e.dropped[0].id === one && /broke the page/.test(e.message));
    assert.equal(sha(fs.readFileSync(path.join(dir, 'components/hero.tsx'))), sha(hero));
  } finally { server.close(); }
});

test('report 1: discard sweeps variant folders a try that died mid-way left behind (never an open session\'s)', async () => {
  const dir = tempSite();
  const at = locate(read(dir, 'components/hero.tsx'), '<section');
  const s = await engine.open(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', count: 1, registry: 'tailark-oss', install: false });
  const stage = path.join(dir, 'components/dh-tryon');
  fs.mkdirSync(path.join(stage, 'orphan-footer-3'), { recursive: true });
  fs.writeFileSync(path.join(stage, 'orphan-footer-3', 'orphan-footer-3.tsx'), 'export default () => null\n');
  const r = engine.discard(dir, s.id);
  assert.deepEqual(r.swept, ['orphan-footer-3']);
  assert.ok(!fs.existsSync(stage));
});

test('report 5: picking an element that is already in a try says so (the old coordinates name its wrapper now)', async () => {
  const dir = tempSite();
  const at = locate(read(dir, 'components/hero.tsx'), '<section');
  const s = await engine.open(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', count: 1, registry: 'tailark-oss', install: false });
  await assert.rejects(engine.open(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', count: 1, registry: 'tailark-oss', install: false }),
    (e) => e.code === 'SESSION_OPEN' && e.id === s.id && /keep or discard/.test(e.message));
  engine.discard(dir, s.id);
});

test('report 8: SVG attributes spelled for HTML are written the way React spells them (no "Invalid DOM property")', () => {
  const out = reactAttrs('a.tsx', `export const X = () => <svg xmlns:xlink="x"><feFlood flood-opacity="0" color-interpolation-filters="sRGB" /><stop stop-color="red" data-k="1" aria-label="a" /><use xlink:href="#a" /><Icon some-prop="1" /><my-el foo-bar="1" /></svg>;`);
  assert.match(out, /xmlnsXlink="x"/);
  assert.match(out, /floodOpacity="0" colorInterpolationFilters="sRGB"/);
  assert.match(out, /stopColor="red" data-k="1" aria-label="a"/);
  assert.match(out, /xlinkHref="#a"/);
  assert.match(out, /<Icon some-prop="1"/, 'a component\'s props are its own');
  assert.match(out, /<my-el foo-bar="1"/, 'a custom element takes attributes as written');
});
