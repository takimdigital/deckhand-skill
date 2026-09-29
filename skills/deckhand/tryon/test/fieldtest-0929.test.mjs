// Field test 2026-09-29: open findings in the try-on engine (F13, F21), each pinned offline.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { tempSite, offline } from './helpers.mjs';
import * as engine from '../lib/engine.mjs';

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
