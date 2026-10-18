// Field test 2026-09-29: open findings in the try-on engine (F13, F21), each pinned offline.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { tempSite, offline } from './helpers.mjs';
import * as engine from '../lib/engine.mjs';
import { createRequire } from 'node:module';
import { parameterize, bind, contentProp } from '../lib/transplant.mjs';

const require = createRequire(import.meta.url);
const { parse } = require('../lib/ast.cjs');

offline();

test('F13: a demo price and a dead href="#" enter the demo ledger (fit counts unchanged)', () => {
  const dir = tempSite();
  const rel = 'components/dh-demo';
  fs.mkdirSync(path.join(dir, rel), { recursive: true });
  fs.writeFileSync(path.join(dir, rel, 'plan.tsx'),
    'export function P() {\n  return (<div><span>$19 / mo</span><a href="#">Docs</a><a href="/menu">Menu</a></div>);\n}\n');
  const ledger = engine.demoTexts(dir, rel, [], { ledger: true }).map((e) => e.text);
  assert.ok(ledger.includes('$19 / mo'), ledger.join(' | '));
  assert.ok(ledger.includes('href="#"'), ledger.join(' | '));
  assert.ok(!ledger.includes('href="/menu"'), 'a real route is not demo copy');
  const plain = engine.demoTexts(dir, rel, []).map((e) => e.text);   // fit counts (demoVisual) must not move
  assert.ok(!plain.includes('$19 / mo') && !plain.includes('href="#"'), plain.join(' | '));
});

test('F21: trying a self-closing usage (<Hero />) says its words live elsewhere; a real section does not', async () => {
  const dir = tempSite();
  const code = 'import { Hero } from "@/components/hero";\n\nexport default function U() {\n  return (\n    <main>\n      <Hero />\n    </main>\n  );\n}\n';
  fs.writeFileSync(path.join(dir, 'app/usage.tsx'), code);
  const at = { line: 6, col: 7 };
  const ins = engine.inspect(dir, { file: 'app/usage.tsx', ...at, slot: 'hero' });
  assert.equal(ins.warning && ins.warning.code, 'EMPTY_USAGE');
  const s = await engine.open(dir, { file: 'app/usage.tsx', ...at, slot: 'hero', count: 1, registry: 'tailark-oss', install: false });
  assert.equal(s.warning && s.warning.code, 'EMPTY_USAGE');
  assert.match(s.warning.message, /its own file/);
  engine.discard(dir, s.id);
  const hero = fs.readFileSync(path.join(dir, 'components/hero.tsx'), 'utf8');
  const i = hero.indexOf('<section');
  const b = hero.slice(0, i);
  const ok = engine.inspect(dir, { file: 'components/hero.tsx', line: b.split('\n').length, col: i - b.lastIndexOf('\n'), slot: 'hero' });
  assert.equal(ok.warning, undefined);
});

test('entry export: a file exporting its parts first ({ BentoCard, BentoGrid }) binds to the export named like the file', async () => {
  const { entryExport } = await import('../lib/materialize.mjs');
  const code = 'const BentoGrid = () => null;\nconst BentoCard = () => null;\nexport { BentoCard, BentoGrid }\n';
  assert.deepEqual(entryExport('components/sections/magicui-bento-grid/magicui-bento-grid.tsx', code), { kind: 'named', name: 'BentoGrid' });
  // no name matches the file: the first component export, as before
  assert.deepEqual(entryExport('x/thing.tsx', 'export const Alpha = () => null;\nexport const Beta = () => null;\n'), { kind: 'named', name: 'Alpha' });
  // a default export still wins over everything
  assert.equal(entryExport('x/bento-grid.tsx', 'export default function Grid() { return null; }\nexport const BentoGrid = () => null;\n').kind, 'default');
});

test('keep: a design array read in TWO places (desktop and mobile menu) is rewritten once and the file still parses', () => {
  // found by a real-browser Keep: the navbar's `menuItems` feeds two `.map`s; its rewrite was queued twice and the
  // overlapping edits wrote `],` + `]` (Unexpected token)
  const dir = tempSite();
  const DESIGN = `const menuItems = [{ name: 'Features', href: '#link' }, { name: 'Solution', href: '#link' }]
export default function Header() {
  return (<header><ul>{menuItems.map((m) => <li key={m.name}><a href={m.href}>{m.name}</a></li>)}</ul><nav>{menuItems.map((m) => <a key={m.name} href={m.href}>{m.name}</a>)}</nav></header>);
}`;
  const p = parameterize('h.tsx', DESIGN, { kind: 'default' }, {});
  parse('h.tsx', p.code);
  assert.ok(/content\.list1 \?/.test(p.code) && /content\.list2 \?/.test(p.code), 'each read of the array is its own list slot: ' + p.code.split('\n').filter((l) => /list\d/.test(l)).join(' | ').slice(0, 300));
  const owner = { units: [], images: [], inputs: [], lists: [], dynamicLists: 0 };
  const ownerList = JSON.stringify([{ name: 'Carte', href: '/menu' }, { name: 'Contact', href: '/contact' }]);
  fs.mkdirSync(path.join(dir, 'components/sections/h'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'components/sections/h/h.tsx'), p.code);
  fs.writeFileSync(path.join(dir, 'app/page.tsx'), `import H from "@/components/sections/h/h"\n\nexport default function Page() {\n  return <main><H content={{ list1: ${ownerList}, list2: ${ownerList} }} /></main>\n}\n`);
  engine.bake(dir, 'app/page.tsx', 'H', { entry: 'components/sections/h/h.tsx', prop: p.prop || 'content' });
  const out = fs.readFileSync(path.join(dir, 'components/sections/h/h.tsx'), 'utf8');
  parse('h.tsx', out);                                                      // the bug: "Unexpected token"
  assert.equal((out.match(/const menuItems = \[/g) || []).length, 1);
  assert.match(out, /name: "Carte"/);
  assert.match(out, /name: "Contact"/);
  assert.ok(!/Features|Solution/.test(out), 'the design\'s demo menu is gone');
});
