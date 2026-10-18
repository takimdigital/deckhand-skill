import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { extractUnits, parameterize, bind, contentProp, contentCount } from '../lib/transplant.mjs';

const require = createRequire(import.meta.url);
const { parse, findElementAt } = require('../lib/ast.cjs');

const ORIGINAL = `import Link from "next/link";
export function Hero({ t }: { t: (k: string) => string }) {
  return (
    <section className="py-24">
      <h1>Bake <span className="text-primary">better</span> bread</h1>
      <p>{t("hero.lead")}</p>
      <Button asChild><Link href="/order">Order now</Link></Button>
      <img src="/bread.jpg" alt="Sourdough" />
    </section>
  );
}`;

const CANDIDATE = `import Link from 'next/link'
import { ChevronRight } from 'lucide-react'
export default function HeroSection() {
  return (
    <section className="bg-zinc-50">
      <h1>Build faster</h1>
      <p>Demo lead copy.</p>
      <div className="flex">
        <Button asChild><Link href="#"><span>Get started</span><ChevronRight /></Link></Button>
        <Button asChild variant="outline"><Link href="#">Book a demo</Link></Button>
      </div>
      <div className="mt-10"><p>Trusted by</p><div className="flex"><Vercel /><Spotify /></div></div>
      <Image src="https://images.unsplash.com/x.jpg" alt="demo" />
    </section>
  )
}`;

function unitsOf(code, needle) {
  const ast = parse('o.tsx', code);
  const i = code.indexOf(needle);
  const before = code.slice(0, i);
  const el = findElementAt(ast, code, before.split('\n').length, i - before.lastIndexOf('\n'));
  return extractUnits(code, el, ast);
}

test('extract keeps inner markup and in-scope expressions verbatim', () => {
  const u = unitsOf(ORIGINAL, '<section');
  assert.deepEqual(u.units.map((x) => x.role), ['heading', 'text', 'action']);
  assert.equal(u.units[0].src, 'Bake <span className="text-primary">better</span> bread');
  assert.equal(u.units[1].src, '{t("hero.lead")}');
  assert.equal(u.units[2].href, '"/order"');
  assert.equal(u.images[0].alt, '"Sourdough"');
});

test('parameterize: slots with demo fallbacks, icon kept beside the label, chrome and logos hidden', () => {
  const p = parameterize('c.tsx', CANDIDATE, { kind: 'default' }, { stripChrome: true, logoLocals: ['Vercel', 'Spotify'] });
  parse('c.tsx', p.code);
  assert.match(p.code, /HeroSection\(\{ content = \{\} \}: \{ content\?: Record<string, any> \} = \{\}\)/);
  assert.match(p.code, /<span>\{content\.action1 \?\? <span data-dh-demo="">Get started<\/span>\}<\/span><ChevronRight \/>/);
  assert.match(p.code, /href=\{content\.action1Href \?\? "#"\}/);
  assert.match(p.code, /\{content\.logos1Show === true && \(<div className="mt-10">/);
  assert.match(p.code, /\{content\.action2Show !== false && \(<Button/);
  assert.deepEqual(p.logoRows, ['logos1']);
  // "Trusted by" sits inside the hidden logo row: it is not offered as a slot
  assert.ok(!p.slots.some((s) => s.demo === 'Trusted by'));
});

test('bind: the owner words land in role order; extra demo buttons hide; demo photos become placeholders', () => {
  const u = unitsOf(ORIGINAL, '<section');
  const p = parameterize('c.tsx', CANDIDATE, { kind: 'default' }, { stripChrome: true, logoLocals: ['Vercel', 'Spotify'] });
  const b = bind(u, p, { placeholder: '/deckhand-placeholder.svg' });
  const props = Object.fromEntries(b.props);
  assert.equal(props.heading1, '<>Bake <span className="text-primary">better</span> bread</>');
  assert.equal(props.text1, '<>{t("hero.lead")}</>');
  assert.equal(props.action1, '<>Order now</>');
  assert.equal(props.action1Href, '"/order"');
  assert.equal(props.action2Show, 'false');
  assert.equal(props.image1, '"/bread.jpg"');
  assert.equal(b.carried.length, contentCount(u));
  assert.ok(b.hidden.includes('Book a demo'));
  const attr = contentProp(p.prop, b.props);
  parse('u.tsx', `const x = <H${attr} />;`);
});

test('lists: a .map over literal data is unrolled and fills repeated cards in order; extra cards hide', () => {
  const orig = `const plans = [
  { name: "Weekly", price: "€9", blurb: "One loaf", perks: ["Free delivery"] },
  { name: "Family", price: "€24", blurb: "Three loaves", perks: [] },
];
export default function P() {
  return (
    <section>
      {plans.map((p) => (
        <div key={p.name}><h3>{p.name}</h3><p>{p.price}</p><p>{p.blurb}</p><ul>{p.perks.map((x) => <li key={x}>{x}</li>)}</ul><button>Subscribe</button></div>
      ))}
    </section>
  );
}`;
  const cand = `export default function Pricing() {
  return (
    <div className="grid">
      <div><p className="font-medium">Starter</p><p>For solo devs</p><div className="text-4xl">$19 <span>/mo</span></div><Button>Get Started</Button><ul>{['A', 'B'].map((i) => <li key={i}>{i}</li>)}</ul></div>
      <div><p className="font-medium">Pro</p><p>For teams</p><div className="text-4xl">$49 <span>/mo</span></div><Button>Get Started</Button><ul>{['C'].map((i) => <li key={i}>{i}</li>)}</ul></div>
      <div><p className="font-medium">Scale</p><p>For orgs</p><div className="text-4xl">$99 <span>/mo</span></div><Button>Get Started</Button><ul>{['D'].map((i) => <li key={i}>{i}</li>)}</ul></div>
    </div>
  )
}`;
  const u = unitsOf(orig, '<section');
  assert.equal(u.lists.length, 1);
  assert.equal(u.lists[0].items.length, 2);
  assert.deepEqual(u.lists[0].items[0].bullets, ['Free delivery']);
  const p = parameterize('c.tsx', cand, { kind: 'default' }, {});
  parse('c.tsx', p.code);
  assert.equal(p.groups[0].count, 3);
  const b = bind(u, p, {});
  const props = Object.fromEntries(b.props);
  const vals = Object.values(props);
  assert.ok(vals.includes('<>Weekly</>') && vals.includes('<>€24</>'));
  assert.equal(props.group1Show3, 'false');
  // price pairs with price, never with a tagline
  const priceKey = Object.keys(props).find((k) => props[k] === '<>€9</>');
  assert.match(priceKey, /^price/);
  assert.equal(props.bullets1, '["Free delivery"]');
  assert.equal(props.bullets2, '[]');                  // no demo features presented as the owner's
});

test('candidate data arrays become list slots merged over the demo items (type-safe cast)', () => {
  const cand = `const features = [{ title: 'Fast', description: 'Demo one', icon: Zap }, { title: 'Safe', description: 'Demo two', icon: Lock }];
export default function F() {
  return (<section><h2>Features</h2><div>{features.map((f) => (<div key={f.title}><f.icon /><h3>{f.title}</h3><p>{f.description}</p></div>))}</div></section>);
}`;
  const orig = `const items = [{ t: "Stone oven", d: "Baked at 280°C" }, { t: "Organic", d: "Local flour" }, { t: "Early", d: "Out by 7am" }];
export default function O() { return (<section><h2>Why us</h2>{items.map((i) => (<article key={i.t}><h3>{i.t}</h3><p>{i.d}</p></article>))}</section>); }`;
  const p = parameterize('c.tsx', cand, { kind: 'default' }, {});
  parse('c.tsx', p.code);
  assert.match(p.code, /\(\(content\.list1 \? content\.list1\.map\(\(o: any, i: number\) => \(\{ \.\.\.features\[i % features\.length\], \.\.\.o \}\)\) : features\) as typeof features\)\.map/);
  const b = bind(unitsOf(orig, '<section'), p, {});
  const props = Object.fromEntries(b.props);
  assert.equal(props.heading1, '<>Why us</>');
  assert.deepEqual(JSON.parse(props.list1), [{ title: 'Stone oven', description: 'Baked at 280°C' }, { title: 'Organic', description: 'Local flour' }, { title: 'Early', description: 'Out by 7am' }]);
});

test('identifier props and object-pattern signatures are both parameterized', () => {
  const a = parameterize('a.tsx', 'export function A(props: Props) { return <h2>x</h2>; }', { kind: 'named', name: 'A' });
  assert.match(a.code, /A\(props: Props & \{ content\?: Record<string, any> \}\)/);
  assert.match(a.code, /props\.content\?\.heading1 \?\?/);
  const b = parameterize('b.tsx', 'export default function B({ className }: { className?: string }) { return <p className={className}>hello there</p>; }', { kind: 'default' });
  assert.match(b.code, /B\(\{ content = \{\}, className \}: \{ className\?: string \} & \{ content\?: Record<string, any> \}\)/);
  const c = parameterize('c.jsx', 'const content = 1; export default function C() { return <p>hello there</p>; }', { kind: 'default' });
  assert.match(c.code, /C\(\{ dhContent = \{\} \} = \{\}\)/);                // name clash -> dhContent, no TS in .jsx
});
