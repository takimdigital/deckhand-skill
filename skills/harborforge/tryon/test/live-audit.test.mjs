// A live audit on three real apps (create-next-app + shadcn, pnpm + src/ without tokens, Vite + React), every
// section, every variant, Tune and Site knob by knob in Chromium. Each thing it found, pinned here offline.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';
import { tempSite, offline, read, locate } from './helpers.mjs';
import * as engine from '../lib/engine.mjs';
import { extractUnits, parameterize, bind, contentProp } from '../lib/transplant.mjs';
import { writeBundle } from '../lib/materialize.mjs';
import { navbarsFromHeroes } from '../lib/regmap.mjs';
import { rank } from '../lib/catalog.mjs';
import { detectProject } from '../lib/project.mjs';
import { tuneElement, tuneOpen, tuneSet, tuneReset, dialsOf } from '../lib/tune.mjs';
import { themeApply, themeUndo, themeState } from '../lib/sitetheme.mjs';
import { detectTarget, startServer } from '../server.mjs';

const require = createRequire(import.meta.url);
const { parse, findElementAt } = require('../lib/ast.cjs');

offline();

function unitsAt(code, needle) {
  const ast = parse('o.tsx', code);
  const i = code.indexOf(needle);
  const b = code.slice(0, i);
  return extractUnits(code, findElementAt(ast, code, b.split('\n').length, i - b.lastIndexOf('\n')), ast);
}
const usageOf = (orig, cand, opts = {}) => { const p = parameterize('c.tsx', cand, { kind: 'default' }, { stripChrome: true, ...opts }); const b = bind(orig, p, {}); return { p, b, usage: `<X${contentProp(p.prop, b.props)} />` }; };

const FAQ_DESIGN = `const faqItems = [
  { id: 'item-1', question: 'How long does shipping take?', answer: 'Standard shipping takes 3-5 business days.' },
  { id: 'item-2', question: 'What payment methods do you accept?', answer: 'We accept all major credit cards.' },
  { id: 'item-3', question: 'Can I change or cancel my order?', answer: 'Yes, within one hour.' },
]
export default function FAQs() {
  return (
    <section className="py-16">
      <h2 className="text-4xl font-semibold">Frequently Asked Questions</h2>
      <Accordion type="single" collapsible>
        {faqItems.map((item) => (
          <AccordionItem key={item.id} value={item.id}>
            <AccordionTrigger>{item.question}</AccordionTrigger>
            <AccordionContent><p>{item.answer}</p></AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </section>
  )
}`;

test('FAQ: a <details><summary> question is a heading — every question and answer lands, no demo question is left', () => {
  const OWNER = `const faqs = [
  { q: "Do you bring your own supplies?", a: "Yes. Eco-certified products are included." },
  { q: "Can we change the schedule?", a: "Any time, with 48 hours notice." },
  { q: "Are you insured?", a: "Yes, up to 2M." },
];
export function Faq() {
  return (
    <section className="py-24">
      <h2 className="text-3xl">Questions</h2>
      {faqs.map((f) => (<details key={f.q}><summary>{f.q}</summary><p>{f.a}</p></details>))}
    </section>
  );
}`;
  const { b, usage } = usageOf(unitsAt(OWNER, '<section'), FAQ_DESIGN);
  assert.equal(b.carried.length, 7);
  assert.deepEqual(b.dropped, []);
  assert.match(usage, /"question": "Do you bring your own supplies\?", "answer": "Yes\. Eco-certified products are included\."/);
  assert.doesNotMatch(usage, /shipping/);
  // two paragraphs per row (no heading at all): the first one is the question
  const TWO_P = OWNER.replace('<details key={f.q}><summary>{f.q}</summary><p>{f.a}</p></details>', '<div key={f.q}><p>{f.q}</p><p>{f.a}</p></div>');
  assert.match(usageOf(unitsAt(TWO_P, '<section'), FAQ_DESIGN).usage, /"question": "Are you insured\?", "answer": "Yes, up to 2M\."/);
});

const TESTIMONIAL_DESIGN = `const testimonials = [
  { avatar: 'https://x.test/a.png', name: 'Meschac Irung', role: 'Frontend Engineer at Acme', quote: 'Tailark has been a game-changer for our team. It has helped us to build a modern and scalable web application.' },
  { avatar: 'https://x.test/b.png', name: 'Theo Balick', role: 'Founder, CEO - Acme', quote: 'Tailark has been a game-changer for our team. It has helped us to build a modern and scalable web application.' },
]
export default function Testimonials() {
  return (
    <section>
      <h2>What Our Customers Say</h2>
      {testimonials.map((t, i) => (
        <div key={i}>
          <img src={t.avatar} alt={t.name} />
          <p className="font-medium">{t.name} <span className="ml-2">{t.role}</span></p>
          <p className="text-sm">{t.quote}</p>
        </div>
      ))}
    </section>
  )
}`;
const OWNER_TESTIMONIALS = `const quotes = [
  { quote: "The first cleaner who sends photos. I stopped checking.", name: "Claire M. · Office manager" },
  { quote: "Same crew every night, and they notice the details.", name: "Hugo R. · COO" },
];
export function Testimonials() {
  return (
    <section className="py-24">
      <h2>What our clients say</h2>
      {quotes.map((q) => (<figure key={q.name}><blockquote>“{q.quote}”</blockquote><figcaption>{q.name}</figcaption></figure>))}
    </section>
  );
}`;

test('testimonials: the quote goes to the quote, the author line to the name; a field the owner has not is shown dashed and reported', () => {
  const orig = unitsAt(OWNER_TESTIMONIALS, '<section');
  assert.deepEqual(orig.lists[0].items[0].units.map((u) => u.role), ['quote', 'text']);     // figcaption = who said it
  const { b, usage } = usageOf(orig, TESTIMONIAL_DESIGN);
  assert.equal(b.carried.length, 5);
  assert.match(usage, /"quote": "“The first cleaner who sends photos\. I stopped checking\.”", "name": "Claire M\. · Office manager"/);
  // the design's "role" line has no owner value: its own words, dashed on the page and listed as demo copy
  assert.match(usage, /"role": <span data-dh-demo="">\{"Frontend Engineer at Acme"\}<\/span>/);
  assert.ok(b.demo.some((d) => d.text === 'Frontend Engineer at Acme'));
  parse('u.tsx', `const X = (p: any) => null; export const Y = () => ${usage};`);
});

test('testimonials: a company logo on each card hides the logo, never the cards', () => {
  const CARDS = `export default function T() {
  return (
    <section>
      <h2>Loved by builders</h2>
      <div className="grid">
        <div><Openai /><p>Congrats on your launch! Looks awesome and the team shipped fast.</p><p>Shekinah T.</p></div>
        <div><Gemini /><p>Great work on the template. This is one of the best I have used.</p><p>Oxymore O.</p></div>
      </div>
    </section>
  )
}`;
  const p = parameterize('t.tsx', CARDS, { kind: 'default' }, { logoLocals: ['Openai', 'Gemini'] });
  assert.ok(p.slots.length >= 4, `slots: ${p.slots.length}`);
  assert.equal(p.logoRows.length, 2);                         // one per logo, not the whole grid
  const b = bind(unitsAt(OWNER_TESTIMONIALS, '<section'), p, {});
  assert.equal(b.carried.length, 5);
});

test('fixed slots take the owner\'s list items whole: a single-card design never gets the second quote as its "role" line', () => {
  const ONE = `export default function T() {
  return (<section><blockquote><p>Using Tailark has been like unlocking a secret design superpower for our team.</p><cite>John Doe</cite><span>Product Designer</span></blockquote></section>)
}`;
  const { b, usage } = usageOf(unitsAt(OWNER_TESTIMONIALS, '<section'), ONE);
  assert.doesNotMatch(usage, /Same crew every night/);
  assert.ok(b.dropped.some((d) => /Same crew every night/.test(d.text)));
});

test('pricing: "Custom" in the price spot is the price; a design\'s span price and "/month" are fields; no double period', () => {
  const OWNER = `const plans = [
  { name: "Studio", price: "€290", period: "/month", blurb: "Up to 150 m²." },
  { name: "Campus", price: "Custom", period: "", blurb: "Several sites." },
];
export function Pricing() {
  return (
    <section>
      {plans.map((p) => (
        <div key={p.name}><h3>{p.name}</h3><p><span className="text-4xl">{p.price}</span><span>{p.period}</span></p><p>{p.blurb}</p></div>
      ))}
    </section>
  );
}`;
  const orig = unitsAt(OWNER, '<section');
  assert.deepEqual(orig.lists[0].items.map((it) => it.units.map((u) => u.role)), [['heading', 'price', 'text'], ['heading', 'price', 'text']]);
  const DESIGN = `const plans = [
  { name: 'Starter', description: 'Perfect for individuals.', price: '$0', period: '/month' },
  { name: 'Pro', description: 'For growing teams.', price: '$29', period: '/month' },
]
export default function P() {
  return (<section><h2>Simple, Transparent Pricing</h2>{plans.map((plan) => (<div key={plan.name}><h3>{plan.name}</h3><p>{plan.description}</p><div><span className="text-4xl">{plan.price}</span><span>{plan.period}</span></div></div>))}</section>)
}`;
  const { p, b, usage } = usageOf(orig, DESIGN);
  assert.deepEqual(p.lists[0].fields.find((f) => f.field === 'price').role, 'price');
  assert.match(usage, /"price": "€290 \/month"/);
  assert.match(usage, /"price": "Custom"/);
  assert.match(usage, /"period": ""/);                          // the owner's price already says "/month"
  assert.equal(b.demo.filter((d) => /\$\d/.test(d.text)).length, 0);
});

test('footer: the owner\'s titled columns fill a design\'s columns, links included; a plan-less site shows no demo menu', () => {
  const OWNER = `import Link from "next/link";
const c = { phone: "+33 1 23 45 67 89", email: "hello@x.fr" };
export function Footer() {
  return (
    <footer>
      <div><p>Contact</p><a href={\`tel:\${c.phone}\`}>{c.phone}</a><a href={\`mailto:\${c.email}\`}>{c.email}</a></div>
      <div><p>Company</p><Link href="/about">About</Link><Link href="/quote">Get a quote</Link></div>
    </footer>
  );
}`;
  const DESIGN = `import Link from 'next/link'
const footerLinks = [
  { name: 'Product', links: [{ href: '#', label: 'Security' }, { href: '#', label: 'Enterprise' }] },
  { name: 'Legal', links: [{ href: '#', label: 'Licence' }, { href: '#', label: 'Privacy Policy' }] },
]
export default function F() {
  return (<footer>{footerLinks.map((g) => (<div key={g.name}><span className="font-medium">{g.name}</span>{g.links.map((l) => (<Link key={l.label} href={l.href}>{l.label}</Link>))}</div>))}</footer>)
}`;
  const { b, usage } = usageOf(unitsAt(OWNER, '<footer'), DESIGN);
  assert.equal(b.carried.length, 6);
  assert.match(usage, /\{ "name": "Contact", "links": \[\{ "href": `tel:\$\{c\.phone\}`, "label": c\.phone \}, \{ "href": `mailto:\$\{c\.email\}`, "label": c\.email \}\] \}/);
  assert.match(usage, /\{ "name": "Company", "links": \[\{ "href": "\/about", "label": "About" \}, \{ "href": "\/quote", "label": "Get a quote" \}\] \}/);
  parse('u.tsx', `const c = { phone: "", email: "" }; const X = (p: any) => null; export const Y = () => ${usage};`);
});

test('catalog: every Tailark hero ships its navbar — derived as navbar designs (GitHub source first)', () => {
  const heroes = [{ id: 'tailark-oss/dusk-hero-section-10@radix', r: 'tailark-oss', n: 'dusk-hero-section-10', base: 'radix', slot: 'hero', t: 'Dusk · hero section 10', rdeps: ['@tailark-oss/dusk-button', '@tailark-oss/dusk-hero-section-10-header', '@tailark-oss/dusk-hero-section-10-logo-cloud'], gh: 'tailark/blocks/main/registry/bases/radix/dusk/blocks/hero-section/ten/hero-section.tsx', json: 'https://oss-tailark.com/r/radix/dusk-hero-section-10', lic: 'MIT' },
    { id: 'tailark-oss/dusk-hero-section-11@radix', r: 'tailark-oss', n: 'dusk-hero-section-11', base: 'radix', slot: 'hero', rdeps: [], gh: 'x/y/z/a.tsx', lic: 'MIT' }];
  const nav = navbarsFromHeroes(heroes);
  assert.equal(nav.length, 1);
  assert.deepEqual(nav[0], { id: 'tailark-oss/dusk-hero-section-10-header@radix', r: 'tailark-oss', n: 'dusk-hero-section-10-header', base: 'radix', slot: 'navbar', kind: 'block', t: 'Dusk · header 10', deps: [], rdeps: ['@tailark-oss/dusk-button'], gh: 'tailark/blocks/main/registry/bases/radix/dusk/blocks/hero-section/ten/header.tsx', json: 'https://oss-tailark.com/r/radix/dusk-hero-section-10-header', lic: 'MIT' });
  const shipped = JSON.parse(fs.readFileSync(new URL('../../data/components.index.json', import.meta.url), 'utf8'));
  assert.ok(shipped.items.filter((i) => i.slot === 'navbar' && /-header@/.test(i.id)).length >= 30, 'the shipped index carries them');
  assert.equal(shipped.count, shipped.items.length);
});

test('ranking: my saved hero ranks first for a hero, not for a CTA', () => {
  const prof = detectProject(tempSite());
  const items = [{ id: 'mine/hero-x@radix', r: 'mine', n: 'hero-x', base: 'radix', slot: 'hero', kind: 'block', deps: [] },
    { id: 'tailark-oss/dusk-call-to-action-1@radix', r: 'tailark-oss', n: 'dusk-call-to-action-1', base: 'radix', slot: 'cta', kind: 'block', deps: [] }];
  assert.equal(rank(items, { slot: 'cta', prof }).items[0].id, 'tailark-oss/dusk-call-to-action-1@radix');
  assert.equal(rank(items, { slot: 'hero', prof }).items[0].id, 'mine/hero-x@radix');
});

test('Vite: a design written for Next gets local next/link and next/image stand-ins, never a missing import', () => {
  const dir = tempSite();
  const pkg = JSON.parse(read(dir, 'package.json'));
  delete pkg.dependencies.next; pkg.devDependencies.vite = '^8';
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify(pkg));
  const prof = detectProject(dir);
  assert.equal(prof.framework, 'vite');
  const st = writeBundle(prof, { r: 'tailark-oss', n: 'hero-x', t: 'Hero X' }, {
    entry: 'blocks/hero.tsx', external: {}, sourceUrl: 'https://example.test', deps: [],
    files: [{ path: 'blocks/hero.tsx', content: `import Link from 'next/link'\nimport Image from 'next/image'\nexport default function H() { return <section><Image src="/a.png" alt="" width={10} height={10} /><Link href="/q">Go</Link></section> }\n` }],
  });
  const code = read(dir, st.entry);
  assert.match(code, /from '\.\/next-link'/);
  assert.match(code, /from '\.\/next-image'/);
  assert.ok(fs.existsSync(path.join(dir, st.relDir, 'next-link.tsx')) && fs.existsSync(path.join(dir, st.relDir, 'next-image.tsx')));
  parse('l.tsx', read(dir, path.posix.join(st.relDir, 'next-link.tsx')));
  // a Next project keeps the real ones
  const nextDir = tempSite();
  const st2 = writeBundle(detectProject(nextDir), { r: 'tailark-oss', n: 'hero-y', t: 'Hero Y' }, {
    entry: 'blocks/hero.tsx', external: {}, sourceUrl: 'https://example.test', deps: [], files: [{ path: 'blocks/hero.tsx', content: `import Link from 'next/link'\nexport default function H() { return <Link href="/q">Go</Link> }\n` }],
  });
  assert.match(read(nextDir, st2.entry), /from 'next\/link'/);
  assert.ok(!fs.existsSync(path.join(nextDir, st2.relDir, 'next-link.tsx')));
});

test('Tune: a Link inside <Button asChild> tunes the Button; a knob with nothing to transform adds its class to a control only', () => {
  const code = 'export const C = () => (<section className="px-6 py-20"><h2 className="text-3xl font-bold">Hi</h2><Button asChild variant="secondary" className="mt-8"><Link href="/q">Go</Link></Button></section>);';
  const ast = parse('c.tsx', code);
  const link = findElementAt(ast, code, 1, code.indexOf('<Link') + 1);
  const btn = engine.styledBy(ast, link);
  assert.equal(btn.start, code.indexOf('<Button'));
  assert.match(tuneElement(code, btn, dialsOf({ corners: 'pill' })).code, /className="mt-8 rounded-full"/);
  assert.match(tuneElement(code, btn, dialsOf({ depth: 'raised', weight: 1 })).code, /className="mt-8 shadow-md font-semibold"/);
  const sec = findElementAt(ast, code, 1, code.indexOf('<section') + 1);
  assert.equal(tuneElement(code, sec, dialsOf({ corners: 'pill' })).changed, 0);   // a section is not rounded behind the owner's back
});

test('Tune: Reset after the owner edited the file puts back only the knob changes and keeps their edit', () => {
  const dir = tempSite();
  const at = locate(read(dir, 'components/hero.tsx'), '<section');
  const o = tuneOpen(dir, { file: 'components/hero.tsx', ...at });
  tuneSet(dir, o.id, { preset: 'airy' });
  const tuned = read(dir, 'components/hero.tsx');
  assert.match(tuned, /py-36/);
  fs.writeFileSync(path.join(dir, 'components/hero.tsx'), tuned.replace('export function Hero', '// the owner typed this\nexport function Hero'));
  assert.throws(() => tuneSet(dir, o.id, { preset: 'bolder' }), (e) => e.code === 'FILE_CHANGED');
  const r = tuneReset(dir, o.id);
  assert.equal(r.mode, 'surgical (your edits kept)');
  const now = read(dir, 'components/hero.tsx');
  assert.match(now, /\/\/ the owner typed this/);
  assert.match(now, /py-24/);
  assert.doesNotMatch(now, /py-36/);
});

test('Site: Undo walks back one apply at a time, to the original, byte-exact', () => {
  const dir = tempSite();
  const css0 = read(dir, 'app/globals.css');
  themeApply(dir, { corners: 'round' });
  const css1 = read(dir, 'app/globals.css');
  themeApply(dir, { corners: 'sharp', accent: 'teal' });
  assert.equal(themeState(dir).undoSteps, 2);
  assert.equal(themeUndo(dir).more, 1);
  assert.equal(read(dir, 'app/globals.css'), css1);
  assert.equal(themeUndo(dir).more, 0);
  assert.equal(read(dir, 'app/globals.css'), css0);
  assert.throws(() => themeUndo(dir), (e) => e.code === 'NO_UNDO');
  // a 2.2.x single-step undo file is still honoured
  fs.mkdirSync(path.join(dir, '.deckhand/tryon/theme'), { recursive: true });
  fs.writeFileSync(path.join(dir, '.deckhand/tryon/theme/last.json'), JSON.stringify({ files: { 'app/globals.css': 'old' } }));
  assert.equal(themeState(dir).undo, true);
  themeUndo(dir);
  assert.equal(read(dir, 'app/globals.css'), 'old');
});

const serve = (handler) => new Promise((r) => { const s = http.createServer(handler); s.listen(0, '127.0.0.1', () => r({ s, url: `http://127.0.0.1:${s.address().port}` })); });

test('the dev server `dh dev start` recorded is found on any port; a typed refusal is an answer (200), not a failed request', async () => {
  const dir = tempSite();
  const dev = await serve((req, res) => { res.writeHead(200, { 'content-type': 'text/html' }); res.end('<html></html>'); });
  try {
    fs.mkdirSync(path.join(dir, '.deckhand'), { recursive: true });
    fs.writeFileSync(path.join(dir, '.deckhand/dev.json'), JSON.stringify({ url: dev.url.replace('127.0.0.1', 'localhost') }));
    assert.equal(await detectTarget(dir), dev.url);
    const helper = await startServer({ root: dir, port: 0, target: dev.url });
    const r = await fetch(`${helper.url}/__dh/api/open`, { method: 'POST', headers: { 'content-type': 'application/json', 'x-dh-token': helper.token }, body: JSON.stringify({ file: 'components/hero.tsx', line: 99, col: 1, slot: 'hero' }) });
    assert.equal(r.status, 200);
    const j = await r.json();
    assert.equal(j.ok, false);
    assert.equal(j.code, 'ELEMENT_NOT_FOUND');
    const bad = await fetch(`${helper.url}/__dh/api/open`, { method: 'POST', headers: { 'content-type': 'application/json', 'x-dh-token': helper.token }, body: '{not json' });
    assert.equal(bad.status, 400);
    helper.server.close();
  } finally { dev.s.close(); }
});

test('Vite build check: the edited module must carry the session, and each design\'s module must resolve its imports', async () => {
  const dir = tempSite();
  const pkg = JSON.parse(read(dir, 'package.json'));
  delete pkg.dependencies.next; pkg.devDependencies.vite = '^8';
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify(pkg));
  const at = locate(read(dir, 'components/hero.tsx'), '<section');
  let victim = null;
  const dev = await serve((req, res) => {
    const u = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    if (u === '/') { res.writeHead(200); res.end('<html><div id="root"></div></html>'); return; }
    const f = path.join(dir, u);
    if (!fs.existsSync(f)) { res.writeHead(404); res.end(); return; }
    const m = /dh-tryon\/([\w-]+)\//.exec(u);
    if (m && (victim = victim || m[1]) === m[1]) { res.writeHead(500); res.end(`{"message":"Failed to resolve import \\"ghost\\" from \\"${u.slice(1)}\\". Does the file exist?"}`); return; }
    res.writeHead(200, { 'content-type': 'text/javascript' });
    res.end(fs.readFileSync(f, 'utf8').replace(/data-dh-session="(\w+)"/g, '"data-dh-session": "$1"'));   // what a JSX compile leaves
  });
  try {
    const s = await engine.openVerified(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', count: 2, registry: 'tailark-oss', install: false, checkImports: false },
      { url: dev.url, page: '/', deadlineMs: 4000 });
    assert.equal(s.verified, true);
    assert.equal(s.dropped.length, 1);
    assert.ok(!s.variants.some((v) => v.id === s.dropped[0].id));
    engine.discard(dir, s.id);
  } finally { dev.s.close(); }
});
