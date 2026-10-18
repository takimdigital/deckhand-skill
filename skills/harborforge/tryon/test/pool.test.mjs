// The pool: More brings the next designs after the ones on screen (never reshuffling or repeating them), up to
// MAX_VARIANTS; an AI draft stays in its place; a spent pool or a full try touches nothing.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { tempSite, offline, read, locate } from './helpers.mjs';
import * as engine from '../lib/engine.mjs';
import * as draft from '../lib/draft.mjs';
import { loadCatalog, rank } from '../lib/catalog.mjs';
import { detectProject } from '../lib/project.mjs';
import { startServer } from '../server.mjs';

const require = createRequire(import.meta.url);
const { parse } = require('../lib/ast.cjs');
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');
offline();

const heroAt = (dir) => ({ file: 'components/hero.tsx', ...locate(read(dir, 'components/hero.tsx'), '<section') });
const ids = (s) => s.variants.slice(1).map((v) => v.id);
const sessionFile = (dir, id) => path.join(dir, '.deckhand/tryon/sessions', id + '.json');

test('open reports the pool (every candidate for the slot here, and how many are untried)', async () => {
  const dir = tempSite();
  const s = await engine.open(dir, { ...heroAt(dir), slot: 'hero', count: 2, registry: 'tailark-oss', install: false });
  const all = rank(loadCatalog(), { slot: 'hero', prof: detectProject(dir), registry: 'tailark-oss' }).items;
  assert.equal(s.pool.total, all.length);
  assert.equal(s.pool.left, all.length - 2);
  assert.equal(s.max, engine.MAX_VARIANTS);
  engine.discard(dir, s.id);
});

test('More: the variants shown keep their places, the new ones come after them, nothing repeats', async () => {
  const dir = tempSite();
  const s = await engine.open(dir, { ...heroAt(dir), slot: 'hero', count: 2, registry: 'tailark-oss', install: false });
  const first = ids(s);
  assert.equal(first.length, 2);
  const m = await engine.more(dir, s.id, { batch: 3 });
  assert.deepEqual(ids(m).slice(0, 2), first, 'the batch the owner saw is back, in the same order');
  assert.ok(m.added >= 1, 'at least one new design');
  assert.equal(m.startAt, 3, 'the bar jumps to the first new one');
  assert.equal(new Set(ids(m)).size, ids(m).length, 'no design twice');
  assert.ok(m.pool.left < s.pool.left);
  // one wrapper, the file still parses, the old session is closed
  const code = read(dir, 'components/hero.tsx');
  parse('hero.tsx', code);
  assert.equal((code.match(/data-dh-session="/g) || []).length, 1);
  assert.equal(JSON.parse(fs.readFileSync(sessionFile(dir, s.id), 'utf8')).state, 'discarded');
  // everything offered is remembered: the next More would skip all of them
  const full = engine.loadSession(dir, m.id);
  for (const id of ids(m)) assert.ok(full.tried.includes(id));
  engine.discard(dir, m.id);
});

test('a failed download is not a verdict on a design: it is not remembered as tried', async () => {
  const dir = tempSite();
  const pool = rank(loadCatalog(), { slot: 'hero', prof: detectProject(dir), registry: 'tailark-oss' }).items;
  const s = await engine.open(dir, { ...heroAt(dir), slot: 'hero', count: 1, install: false,
    candidates: [{ id: 'nope/none@radix', r: 'nope', n: 'none', t: 'None', slot: 'hero', kind: 'block', json: 'https://example.invalid/r/none.json' }, ...pool] });
  const full = engine.loadSession(dir, s.id);
  assert.ok(full.skipped.some((k) => k.id === 'nope/none@radix'));
  assert.ok(!full.tried.includes('nope/none@radix'));
  assert.ok(full.tried.includes(ids(s)[0]));
  engine.discard(dir, s.id);
});

test('a spent pool or a full try: More refuses and leaves the session and the file exactly as they were', async () => {
  const dir = tempSite();
  const s = await engine.open(dir, { ...heroAt(dir), slot: 'hero', count: 1, registry: 'tailark-oss', install: false });
  const file = path.join(dir, 'components/hero.tsx');
  const before = fs.readFileSync(file);
  const full = engine.loadSession(dir, s.id);
  // every design of the pool already offered
  const all = rank(loadCatalog(), { slot: 'hero', prof: detectProject(dir), registry: 'tailark-oss' }).items.map((x) => x.id);
  fs.writeFileSync(sessionFile(dir, s.id), JSON.stringify({ ...full, tried: all }, null, 2));
  await assert.rejects(engine.more(dir, s.id, { batch: 4 }), (e) => e.code === 'POOL_EMPTY' && /already been shown/.test(e.message));
  assert.equal(sha(fs.readFileSync(file)), sha(before));
  assert.equal(engine.loadSession(dir, s.id).state, 'open');
  // the most one try holds
  const many = Array.from({ length: engine.MAX_VARIANTS }, (_, i) => ({ ...full.variants[0], idx: i + 1 }));
  fs.writeFileSync(sessionFile(dir, s.id), JSON.stringify({ ...full, variants: many }, null, 2));
  await assert.rejects(engine.more(dir, s.id, { batch: 4 }), (e) => e.code === 'TOO_MANY_VARIANTS' && e.max === engine.MAX_VARIANTS);
  assert.equal(sha(fs.readFileSync(file)), sha(before));
  fs.writeFileSync(sessionFile(dir, s.id), JSON.stringify(full, null, 2));
  engine.discard(dir, s.id);
  assert.equal(engine.MAX_VARIANTS, 30);
});

test('open: count is capped at MAX_VARIANTS; `only` stages exactly the designs named (the reproduce command)', async () => {
  const dir = tempSite();
  const want = 'tailark-oss/mist-hero-section-1@radix';
  const s = await engine.open(dir, { ...heroAt(dir), slot: 'hero', count: 99, only: want, install: false });
  assert.deepEqual(ids(s), [want]);
  engine.discard(dir, s.id);
  // the registry-less id (as a report prints it) works too
  const t = await engine.open(dir, { ...heroAt(dir), slot: 'hero', count: 4, only: ['tailark-oss/mist-hero-section-1'], install: false });
  assert.deepEqual(ids(t), [want]);
  engine.discard(dir, t.id);
  await assert.rejects(engine.open(dir, { ...heroAt(dir), slot: 'hero', only: 'nobody/nothing', install: false }), (e) => e.code === 'NO_CANDIDATES');
});

test('More keeps an AI draft in its place (re-staged from the draft files) beside the registry variants', async () => {
  const dir = tempSite();
  const s = await engine.open(dir, { ...heroAt(dir), slot: 'hero', count: 1, registry: 'tailark-oss', install: false });
  const r = draft.requestDraft(dir, { session: s.id });
  fs.writeFileSync(path.join(dir, r.write_to, 'draft.tsx'), `import Link from "next/link";
export default function HeroDraft() {
  return (
    <section className="px-6 py-20 text-foreground">
      <h1 className="text-5xl">Sourdough delivered <span className="text-primary">warm</span> to your door</h1>
      <p className="mt-4 text-muted-foreground">Maison Levain bakes every loaf at 4am and delivers across Lyon before breakfast.</p>
      <Link href="/order" className="bg-primary text-primary-foreground">Order your first loaf</Link>
      <Link href="#menu">See the menu</Link>
      <img src="/deckhand-placeholder.svg" alt="Bread on a table" />
    </section>
  );
}
`);
  const d = await draft.completeDraft(dir, r.id);
  const aiIdx = d.ai_variant;
  const aiId = d.variants[aiIdx].id;
  const m = await engine.more(dir, d.id, { batch: 2 });
  assert.equal(m.variants[aiIdx].id, aiId, 'the AI draft is where it was');
  assert.equal(m.variants[aiIdx].generated, true);
  assert.ok(m.added >= 1);
  engine.discard(dir, m.id);
});

test('helper: the More API appends to the open session and the page is proven to still build', async () => {
  const dir = tempSite();
  // a dev server stand-in that renders what is on disk now (the wrapper appears once it is written)
  const up = http.createServer((req, res) => {
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end('<html><head></head><body>' + fs.readFileSync(path.join(dir, 'components/hero.tsx'), 'utf8').replace(/</g, '&lt;') + '</body></html>');
  });
  await new Promise((r) => up.listen(0, '127.0.0.1', r));
  const target = `http://127.0.0.1:${up.address().port}`;
  const { server, url, token } = await startServer({ root: dir, port: 0, target });
  const call = async (name, body) => (await fetch(url + '/__dh/api/' + name, { method: 'POST', headers: { 'content-type': 'application/json', 'x-dh-token': token }, body: JSON.stringify(body) })).json();
  try {
    const o = await call('open', { ...heroAt(dir), slot: 'hero', count: 1, registry: 'tailark-oss', install: false, page: '/' });
    assert.equal(o.ok, true, o.message);
    const m = await call('more', { id: o.id, batch: 2, page: '/' });
    assert.equal(m.ok, true, m.message);
    assert.equal(m.variants[1].id, o.variants[1].id);
    assert.ok(m.added >= 1);
    assert.equal(m.startAt, 2);
    assert.equal(m.verified, true);
    const st = await (await fetch(url + '/__dh/api/state', { headers: { 'x-dh-token': token } })).json();
    assert.deepEqual(st.open.map((x) => x.id), [m.id]);
    assert.ok(st.open[0].pool && st.open[0].pool.total > 0);
    const bad = await call('more', { id: 'nosuch' });
    assert.equal(bad.ok, false);
    assert.equal(bad.code, 'NO_SESSION');
    await call('discard', { id: m.id });
  } finally {
    server.close();
    up.close();
  }
});
