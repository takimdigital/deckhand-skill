import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { parameterize, bind, contentProp } from '../lib/transplant.mjs';
import { bake } from '../lib/engine.mjs';
import { siteLinks, fillLinks, linkTexts } from '../lib/sitelinks.mjs';
import { tempSite, read } from './helpers.mjs';

const require = createRequire(import.meta.url);
const { parse } = require('../lib/ast.cjs');

/** The owner's section as compose builds it from copy.json (heading, subtitle, 4 cards). */
const item = (title, text) => ({ units: [{ role: 'heading', text: title, src: title, list: 0 }, { role: 'text', text, src: text, list: 0 }], images: [], bullets: [] });
const OWNER = (() => {
  const items = [item('Baked at 4am', 'Out of the oven at dawn.'), item('48-hour ferment', 'Slow leaven.'), item('Local flour', 'Stone-milled.'), item('Zero waste', 'Linen bags.')];
  const units = [{ role: 'heading', text: 'Why Lyon wakes up to Levain', src: 'Why Lyon wakes up to Levain', list: null },
    { role: 'text', text: 'Real bread before 7am.', src: 'Real bread before 7am.', list: null }];
  items.forEach((it, i) => it.units.forEach((u) => units.push({ ...u, item: i })));
  return { units, images: [], inputs: [], lists: [{ items }], dynamicLists: 0 };
})();

const TWIN_ROWS = `export default function Features() {
  return (
    <section>
      <h2 className="text-muted-foreground"><span className="text-foreground">Every deal, one view.</span> <br /> Stages and owners in one place.</h2>
      <div className="grid grid-cols-2 gap-3 border">
        <div><h3>One pipeline view.</h3><p>See every deal stage.</p></div>
        <div><h3>Customer signals.</h3><p>Notes stay linked.</p></div>
      </div>
      <div className="grid grid-cols-4 gap-6">
        <div><h3>Pipeline visibility.</h3><p>Every open deal.</p></div>
        <div><h3>Account history.</h3><p>Every email.</p></div>
        <div><h3>Team alignment.</h3><p>Shared context.</p></div>
        <div><h3>Forecast health.</h3><p>Spot risk.</p></div>
      </div>
    </section>
  )
}`;

test('twin card rows are one list: 4 items take the 4-up row, the 2-up row hides whole', () => {
  const p = parameterize('f.tsx', TWIN_ROWS, { kind: 'default' }, {});
  parse('f.tsx', p.code);
  assert.deepEqual(p.groups.map((g) => [g.key, g.count, g.box]), [['group1', 2, true], ['group2', 4, true]]);
  const b = bind(OWNER, p, {});
  const props = Object.fromEntries(b.props);
  assert.equal(props.group1BoxShow, 'false');
  assert.equal(props.group1Show1, 'false');
  assert.equal(b.carried.length, 10, 'heading + subtitle + 4 x (title, text)');
  assert.deepEqual(b.dropped, []);
  assert.deepEqual(b.demo, []);
});

test('a two-tone heading takes the heading in its bright half and the subtitle in its muted half', () => {
  const p = parameterize('f.tsx', TWIN_ROWS, { kind: 'default' }, {});
  const h = p.slots.filter((s) => s.group == null && (s.role === 'heading' || s.role === 'text'));
  assert.deepEqual(h.map((s) => [s.role, s.sub, !!s.optional]), [['heading', 'lead', false], ['text', null, true]]);
  const props = Object.fromEntries(bind(OWNER, p, {}).props);
  assert.equal(props[h[0].key], '<>Why Lyon wakes up to Levain</>');
  assert.equal(props[h[1].key], '<>Real bread before 7am.</>');
  // no subtitle -> the muted half renders nothing (never the design's demo words)
  const noSub = { ...OWNER, units: OWNER.units.filter((u) => u.text !== 'Real bread before 7am.') };
  assert.equal(Object.fromEntries(bind(noSub, p, {}).props)[h[1].key], 'false');
});

test('bake: empty optional half, hidden row and unwired form leave no demo copy and still parse', () => {
  const dir = tempSite();
  const code = TWIN_ROWS.replace('</section>', '<form className="mt-8"><input placeholder="Your email" /><button>Subscribe</button></form></section>');
  const p = parameterize('f.tsx', code, { kind: 'default' }, { forms: 'hide' });
  assert.deepEqual(p.forms, ['form1']);
  const noSub = { ...OWNER, units: OWNER.units.filter((u) => u.text !== 'Real bread before 7am.') };
  const b = bind(noSub, p, {});
  assert.ok(b.hidden.some((h) => /form/.test(h)));
  fs.mkdirSync(path.join(dir, 'components/sections/f'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'components/sections/f/f.tsx'), p.code);
  fs.writeFileSync(path.join(dir, 'app/page.tsx'), `import F from "@/components/sections/f/f"\n\nexport default function Page() {\n  return <main><F${contentProp(p.prop, b.props)} /></main>\n}\n`);
  bake(dir, 'app/page.tsx', 'F', { entry: 'components/sections/f/f.tsx', prop: p.prop });
  const out = read(dir, 'components/sections/f/f.tsx');
  parse('f.tsx', out);
  for (const demo of ['Stages and owners', 'One pipeline view', 'Pipeline visibility', 'Subscribe', 'Your email', 'data-dh-demo', 'content']) assert.ok(!out.includes(demo), demo);
  assert.match(out, /<span className="text-foreground">Why Lyon wakes up to Levain<\/span>/);
  assert.match(out, /Baked at 4am/);
  assert.match(read(dir, 'app/page.tsx'), /<F \/>/);
});

const FOOTER = `import Link from 'next/link'
const community = [
  { href: '#', label: 'GitHub', icon: <svg /> },
  { href: '#', label: 'Instagram', icon: <svg /> },
  { href: '#', label: 'X / Twitter', icon: <svg /> },
]
const columns = [
  { name: 'Product', links: [{ href: '#', label: 'Security' }, { href: '#', label: 'Enterprise' }] },
  { name: 'Company', links: [{ href: '#', label: 'About' }] },
]
export default function Footer() {
  return <footer>{columns.map((c) => <div key={c.name}>{c.name}{c.links.map((l) => <Link key={l.label} href={l.href}>{l.label}</Link>)}</div>)}{community.map((l) => <a key={l.label} href={l.href}>{l.icon}</a>)}</footer>
}`;

test('footer menus come from the plan; social rows keep only the networks the owner is on', () => {
  const dir = tempSite();
  fs.mkdirSync(path.join(dir, '.deckhand'), { recursive: true });
  fs.writeFileSync(path.join(dir, '.deckhand/sitemap.json'), JSON.stringify({
    nav: { header: ['route:/', 'route:/menu', 'route:/order'], footer: ['route:/legal', 'mailto:bonjour@levain.fr'] },
    pages: [{ route: '/', title: 'Home' }, { route: '/menu', title: 'Menu' }, { route: '/order', title: 'Order' }, { route: '/legal', title: 'Legal' }, { route: '/p/[id]', title: 'Product' }],
  }));
  fs.writeFileSync(path.join(dir, '.deckhand/brief.json'), JSON.stringify({ brand: { name: 'Maison Levain', social: { instagram: 'https://instagram.com/levain' } } }));
  const links = siteLinks(dir);
  assert.deepEqual(links.header.map((l) => l.href), ['/menu', '/order']);
  assert.deepEqual(links.footerCols, [{ title: 'Maison Levain', links: [{ label: 'Menu', href: '/menu' }, { label: 'Order', href: '/order' }, { label: 'Legal', href: '/legal' }, { label: 'bonjour@levain.fr', href: 'mailto:bonjour@levain.fr' }] }]);
  const r = fillLinks('footer.tsx', FOOTER, links, 'footer');
  parse('footer.tsx', r.code);
  assert.deepEqual(r.filled.map((f) => [f.array, f.kind, f.count]), [['community', 'social', 1], ['columns', 'columns', 1]]);
  assert.match(r.code, /\{ href: "https:\/\/instagram\.com\/levain", label: "Instagram", icon: <svg \/> \}/);
  for (const demo of ['GitHub', 'Twitter', 'Security', 'Enterprise', 'Company', "'#'"]) assert.ok(!r.code.includes(demo), demo);
  assert.ok(linkTexts(links).includes('Maison Levain'));
  // nobody on social media -> a typed empty row (a bare [] would be never[] in TypeScript)
  fs.writeFileSync(path.join(dir, '.deckhand/brief.json'), JSON.stringify({ brand: { name: 'Maison Levain' } }));
  assert.match(fillLinks('footer.tsx', FOOTER, siteLinks(dir), 'footer').code, /const community = \(\[\] as Array<\{ href: string; label: string; \[k: string\]: any \}>\)/);
  // a navbar's flat menu gets the plan's header (home is the logo's job)
  const NAV = `const menuItems = [{ name: 'Features', href: '#link' }, { name: 'Solution', href: '#link' }]\nexport default function H() { return <nav>{menuItems.map((m) => <a key={m.name} href={m.href}>{m.name}</a>)}</nav> }`;
  const nav = fillLinks('h.tsx', NAV, links, 'navbar');
  assert.deepEqual(nav.filled, [{ array: 'menuItems', kind: 'menu', count: 2 }]);
  assert.match(nav.code, /const menuItems = \[\{ href: "\/menu", name: "Menu" \}, \{ href: "\/order", name: "Order" \}\]/);
  assert.equal(fillLinks('h.tsx', NAV, links, 'hero').code, NAV, 'only footer/navbar menus are rewritten');
  // no plan, no brief -> nothing is invented, and the design's demo menus are not passed off as the owner's:
  // emptied (typed), so the owner's own links (carried by the content slots) are the only ones on the page
  assert.equal(siteLinks(tempSite()), null);
  const none = fillLinks('footer.tsx', FOOTER, null, 'footer');
  parse('footer.tsx', none.code);
  assert.deepEqual(none.filled.map((f) => [f.array, f.kind, f.count, f.demoHidden]), [['community', 'social', 0, undefined], ['columns', 'columns', 0, 2]]);
  for (const demo of ['GitHub', 'Security', 'Enterprise', 'Product']) assert.ok(!none.code.includes(demo), demo);
  assert.match(none.code, /const columns = \(\[\] as Array<\{ name: string; links: Array<\{ href: string; label: string; \[k: string\]: any \}>; \[k: string\]: any \}>\)/);
  assert.match(fillLinks('h.tsx', NAV, null, 'navbar').code, /const menuItems = \(\[\] as Array/);
});
