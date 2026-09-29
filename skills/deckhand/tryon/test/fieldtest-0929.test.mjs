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
