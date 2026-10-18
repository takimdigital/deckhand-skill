import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { tempSite, offline, read, locate } from './helpers.mjs';
import * as engine from '../lib/engine.mjs';
import { saveToLibrary, listLibrary } from '../lib/library.mjs';

const require = createRequire(import.meta.url);
const { parse } = require('../lib/ast.cjs');
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');

offline();

test('open -> wrapper written once, variants carry the owner text, file parses; discard is byte-exact', async () => {
  const dir = tempSite();
  const before = fs.readFileSync(path.join(dir, 'components/hero.tsx'));
  const cssBefore = read(dir, 'app/globals.css');
  const at = locate(before.toString(), '<section');
  const s = await engine.open(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', count: 2, registry: 'tailark-oss', install: false });
  assert.equal(s.variants.length, 3);                                  // original + 2
  for (const v of s.variants.slice(1)) assert.equal(v.fit.carried, v.fit.of, `${v.t} carries every unit`);
  const code = read(dir, 'components/hero.tsx');
  parse('hero.tsx', code);
  assert.match(code, /data-dh-session="/);
  assert.match(code, /heading1: <>\s*Sourdough delivered <span className="text-amber-600">warm<\/span> to your door\s*<\/>/);
  assert.match(code, /action1Href: "\/order"/);
  // the site got semantic tokens derived from its own colours
  assert.match(read(dir, 'app/globals.css'), /deckhand:tokens/);
  assert.notEqual(read(dir, 'app/globals.css'), cssBefore);
  // staged files carry attribution; demo photo replaced by the neutral placeholder
  const staged = fs.readdirSync(path.join(dir, 'components/dh-tryon'));
  assert.equal(staged.length, 2);
  assert.ok(fs.existsSync(path.join(dir, 'public/deckhand-placeholder.svg')));
  const entry = read(dir, `components/dh-tryon/${staged[0]}/${staged[0]}.tsx`);
  assert.match(entry, /\(MIT\) · source: https:\/\/github\.com\/tailark\/blocks/);
  const r = engine.discard(dir, s.id);
  assert.equal(r.mode, 'byte-exact');
  assert.equal(sha(fs.readFileSync(path.join(dir, 'components/hero.tsx'))), sha(before));
  assert.ok(!fs.existsSync(path.join(dir, 'components/dh-tryon')));
});

test('show persists the visible variant; keep bakes literal copy, graduates the folder, records the licence', async () => {
  const dir = tempSite();
  const at = locate(read(dir, 'components/hero.tsx'), '<section');
  const s = await engine.open(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', count: 2, registry: 'tailark-oss', install: false });
  engine.show(dir, s.id, 2);
  assert.match(read(dir, 'components/hero.tsx'), /data-dh-variant="2"[^\n]*display: "contents"/);
  const k = engine.keep(dir, s.id, 2);
  assert.equal(k.ok, true);
  const hero = read(dir, 'components/hero.tsx');
  parse('hero.tsx', hero);
  assert.doesNotMatch(hero, /data-dh-session|dh-tryon/);
  assert.match(hero, /from "@\/components\/sections\//);
  assert.match(hero, new RegExp(`<${k.local} />`));                        // every value was literal -> no props left
  const comp = read(dir, k.component);
  parse('c.tsx', comp);
  assert.match(comp, /Sourdough delivered <span className="text-amber-600">warm<\/span> to your door/);
  assert.match(comp, /href="\/order"/);
  assert.doesNotMatch(comp, /content\.|dh-demo|staged by deckhand/);
  assert.match(read(dir, 'THIRD_PARTY_NOTICES.md'), /tailark\/blocks[\s\S]*Permission is hereby granted/);
  assert.ok(!fs.existsSync(path.join(dir, 'components/dh-tryon')));
  // save to the personal library -> ranks first next time
  const saved = saveToLibrary(dir, s.id);
  assert.match(saved.saved, /^mine\//);
  assert.ok(listLibrary().some((i) => i.id === saved.saved));
});

test('pricing from a .map over literal data: every plan, price and blurb lands in the right card', async () => {
  const dir = tempSite();
  const at = locate(read(dir, 'app/page.tsx'), '<section id="pricing"');
  const s = await engine.open(dir, { file: 'app/page.tsx', ...at, slot: 'pricing', count: 1, registry: 'tailark-oss', install: false });
  const v = s.variants[1];
  assert.equal(v.fit.carried, v.fit.of);
  const page = read(dir, 'app/page.tsx');
  parse('page.tsx', page);
  assert.match(page, /price1: <>€9<\/>/);
  assert.match(page, /price2: <>€24<\/>/);
  assert.match(page, /group1Show3: false/);
  engine.discard(dir, s.id);
});

test('refusals are typed and write nothing', async () => {
  const dir = tempSite();
  const before = read(dir, 'components/hero.tsx');
  await assert.rejects(engine.open(dir, { file: 'components/hero.tsx', line: 99, col: 1, slot: 'hero' }), /ELEMENT_NOT_FOUND|no JSX element/);
  await assert.rejects(engine.open(dir, { file: '../etc/passwd', line: 1, col: 1, slot: 'hero' }), (e) => e.code === 'OUTSIDE_PROJECT');
  await assert.rejects(engine.open(dir, { file: 'components/hero.tsx', line: 6, col: 5, slot: '' }), (e) => e.code === 'NO_SLOT');
  assert.equal(read(dir, 'components/hero.tsx'), before);
  assert.throws(() => engine.keep(dir, 'nope', 1), (e) => e.code === 'NO_SESSION');
});

test('discard after the owner edited the file unwraps surgically and keeps their edit', async () => {
  const dir = tempSite();
  const at = locate(read(dir, 'components/hero.tsx'), '<section');
  const s = await engine.open(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', count: 1, registry: 'tailark-oss', install: false });
  const f = path.join(dir, 'components/hero.tsx');
  fs.writeFileSync(f, fs.readFileSync(f, 'utf8').replace('export function Hero()', '// owner note\nexport function Hero()'));
  const r = engine.discard(dir, s.id);
  assert.match(r.mode, /surgical/);
  const code = read(dir, 'components/hero.tsx');
  parse('hero.tsx', code);
  assert.match(code, /\/\/ owner note/);
  assert.doesNotMatch(code, /dh-tryon|data-dh-session/);
  assert.match(code, /<section className="mx-auto max-w-3xl/);
});
