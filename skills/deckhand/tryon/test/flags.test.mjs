// Flags: a variant that does not work is captured with everything needed to reproduce it, and the flags become ONE
// deterministic Markdown report (patterns first) that stays on the owner's machine.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { tempSite, offline, read, locate } from './helpers.mjs';
import * as engine from '../lib/engine.mjs';
import { REASONS, addFlag, listFlags, publicFlag, removeFlag, clearFlags, buildReport, designSlots } from '../lib/flags.mjs';
import { startServer } from '../server.mjs';

offline();
const CLI = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'cli.mjs');

async function heroSession(dir, count = 2) {
  return engine.open(dir, { file: 'components/hero.tsx', ...locate(read(dir, 'components/hero.tsx'), '<section'), slot: 'hero', count, registry: 'tailark-oss', install: false });
}
const AUTO = { missing: ['Order your first loaf'], foreign: ['Introducing Support for AI Models'], overflow: 3, brokenImages: ['/x.png'], errors: ['TypeError: x is undefined'], viewport: { w: 390, h: 844 } };

test('a flag captures where, the design, the fit, the owner element (from the backup), the design slots and the page check', async () => {
  const dir = tempSite();
  const s = await heroSession(dir);
  const f = addFlag(dir, { session: s.id, idx: 1, reasons: ['layout', 'missing'], note: 'the button is gone', auto: AUTO });
  assert.match(f.id, /^F[0-9a-f]{8}$/);
  assert.deepEqual(f.reasons, ['missing', 'layout'], 'reasons in their canonical order');
  assert.equal(f.total, 1);
  const raw = JSON.parse(read(dir, '.deckhand/tryon/flags.json')).flags[0];
  assert.equal(raw.where.file, 'components/hero.tsx');
  assert.equal(raw.where.slot, 'hero');
  assert.equal(raw.variant.id, s.variants[1].id);
  assert.equal(raw.variant.licence, 'MIT');
  assert.match(raw.variant.source, /^https:\/\//);
  assert.match(raw.owner.jsx, /^<section/);
  assert.doesNotMatch(raw.owner.jsx, /data-dh-session/, 'the element as it was, not the wrapper');
  assert.ok(raw.owner.units.some((u) => u.role === 'heading' && /Sourdough delivered/.test(u.text)));
  assert.ok(raw.design.slots.length > 0);
  assert.match(raw.design.code, /content/);
  assert.match(raw.usage, /heading1/);
  assert.deepEqual(raw.auto.missing, AUTO.missing);
  assert.equal(raw.auto.overflow, 3);
  assert.equal(raw.env.framework, 'next');
  assert.match(raw.env.deckhand, /^\d+\.\d+\.\d+$/);
  // flagging the same design again replaces the flag
  const g = addFlag(dir, { session: s.id, idx: 1, reasons: ['style'] });
  assert.equal(g.id, f.id);
  assert.equal(listFlags(dir).length, 1);
  assert.deepEqual(listFlags(dir)[0].reasons, ['style']);
  engine.discard(dir, s.id);
});

test('flags refuse the original, unknown reasons, an empty flag; remove and clear', async () => {
  const dir = tempSite();
  const s = await heroSession(dir);
  assert.throws(() => addFlag(dir, { session: s.id, idx: 0, reasons: ['layout'] }), (e) => e.code === 'NO_VARIANT');
  assert.throws(() => addFlag(dir, { session: s.id, idx: 1, reasons: ['ugly'] }), (e) => e.code === 'BAD_REASON' && e.allowed.includes('layout'));
  assert.throws(() => addFlag(dir, { session: s.id, idx: 1, reasons: [], note: '  ' }), (e) => e.code === 'NO_REASON');
  assert.throws(() => addFlag(dir, { session: 'nope', idx: 1, reasons: ['layout'] }), (e) => e.code === 'NO_SESSION');
  const a = addFlag(dir, { session: s.id, idx: 1, reasons: ['layout'] });
  const b = addFlag(dir, { session: s.id, idx: 2, note: 'odd spacing' });
  assert.notEqual(a.id, b.id);
  assert.equal(removeFlag(dir, a.id).total, 1);
  assert.throws(() => removeFlag(dir, a.id), (e) => e.code === 'NO_FLAG');
  assert.deepEqual(clearFlags(dir), { cleared: 1, total: 0 });
  assert.throws(() => buildReport(dir), (e) => e.code === 'NO_FLAGS');
  engine.discard(dir, s.id);
});

test('the report: deterministic bytes named by their hash, summary, patterns, details and a reproduce command', async () => {
  const dir = tempSite();
  const s = await heroSession(dir);
  addFlag(dir, { session: s.id, idx: 1, reasons: ['missing', 'layout'], note: 'the | pipe and ``` fences are safe', auto: AUTO });
  addFlag(dir, { session: s.id, idx: 2, reasons: ['layout'] });
  engine.discard(dir, s.id);                                        // flags outlive the session
  const r1 = buildReport(dir);
  const r2 = buildReport(dir);
  assert.equal(r1.markdown, r2.markdown, 'same flags, same bytes');
  assert.equal(r1.path, r2.path);
  assert.match(r1.path, /^\.deckhand\/tryon\/reports\/tryon-flags-[0-9a-f]{10}\.md$/);
  assert.equal(read(dir, r1.path), r1.markdown);
  const md = r1.markdown;
  assert.doesNotMatch(md, /\d{4}-\d{2}-\d{2}T\d{2}:/, 'no clock in the report');
  assert.match(md, /^# Try-on flag report\n/);
  assert.match(md, /Fix the\n> engine/);
  assert.match(md, /\| F1 \| hero \|/);
  assert.match(md, /\| F2 \| hero \|/);
  assert.match(md, new RegExp(`- \\*\\*${REASONS.layout}\\*\\* \\(2\\): F1, F2`), 'the pattern across both flags comes first');
  assert.match(md, /### By registry\n- \*\*tailark-oss\*\* \(2\)/);
  assert.match(md, /The owner says: “the \| pipe and ``` fences are safe”/);
  assert.match(md, /words of the owner not on the page: “Order your first loaf”/);
  assert.match(md, /3 element\(s\) wider than the screen/);
  assert.match(md, /### The owner's element, before the try\n\n````?tsx\n<section/);
  assert.match(md, /--only tailark-oss\/[\w-]+@radix --no-verify/);
  // every code fence closes (a design's template literal never breaks the file)
  for (const m of md.matchAll(/^(`{3,})\w*$/gm)) assert.ok(md.indexOf('\n' + m[1] + '\n', m.index + 1) > 0 || md.endsWith(m[1] + '\n'));
  // a subset by id
  const one = buildReport(dir, [listFlags(dir)[0].id]);
  assert.equal(one.flags, 1);
  assert.notEqual(one.path, r1.path);
});

test('designSlots reads a staged design: each content slot and the demo words it falls back to', () => {
  const code = `export default function X({ content = {} }) {
  return <section>
    <h1>{content.heading1 ?? <span data-dh-demo="">Build <b>faster</b> today</span>}</h1>
    <p>{content.text1 ?? "Ship it"}</p>
    <a href={content.action1Href ?? '#'}>{content.action1 ?? <>Start</>}</a>
    {content.heading1 && <i />}
  </section>;
}`;
  assert.deepEqual(designSlots(code), [
    { slot: 'action1', demo: 'Start' }, { slot: 'action1Href', demo: '#' }, { slot: 'heading1', demo: 'Build faster today' }, { slot: 'text1', demo: 'Ship it' },
  ]);
});

test('helper + CLI: flag-add / flags / flag-report / flag-remove / flags-clear; `flags report` writes the same file', async () => {
  const dir = tempSite();
  const up = await import('node:http').then((h) => h.createServer((q, s) => { s.writeHead(200, { 'content-type': 'text/html' }); s.end('<html><head></head><body>x</body></html>'); }));
  await new Promise((r) => up.listen(0, '127.0.0.1', r));
  const { server, url, token } = await startServer({ root: dir, port: 0, target: `http://127.0.0.1:${up.address().port}` });
  const call = async (name, body) => (await fetch(url + '/__dh/api/' + name, { method: body ? 'POST' : 'GET', headers: { 'content-type': 'application/json', 'x-dh-token': token }, body: body ? JSON.stringify(body) : undefined })).json();
  try {
    const s = await heroSession(dir);
    const empty = await call('flags');
    assert.deepEqual(empty.flags, []);
    assert.deepEqual(Object.keys(empty.reasons), Object.keys(REASONS));
    const bad = await call('flag-add', { session: s.id, idx: 1, reasons: ['nope'] });
    assert.equal(bad.ok, false);
    assert.equal(bad.code, 'BAD_REASON');
    assert.ok(bad.allowed.includes('missing'));
    const f = await call('flag-add', { session: s.id, idx: 1, reasons: ['foreign'], auto: AUTO });
    assert.equal(f.ok, true, f.message);
    const list = await call('flags');
    assert.deepEqual(list.flags.map((x) => x.id), [f.id]);
    assert.deepEqual(list.flags[0], publicFlag(listFlags(dir)[0]));
    const rep = await call('flag-report', {});
    assert.equal(rep.ok, true);
    assert.match(rep.markdown, /it shows words that aren't mine/);
    // the CLI writes the very same report
    const c = spawnSync(process.execPath, [CLI, 'flags', 'report', '--project', dir], { encoding: 'utf8', env: process.env });
    const o = JSON.parse(c.stdout);
    assert.equal(o.ok, true);
    assert.equal(o.path, rep.path);
    const l = JSON.parse(spawnSync(process.execPath, [CLI, 'flags', 'list', '--project', dir], { encoding: 'utf8', env: process.env }).stdout);
    assert.equal(l.flags.length, 1);
    assert.equal((await call('flag-remove', { id: f.id })).total, 0);
    await call('flag-add', { session: s.id, idx: 2, note: 'x' });
    assert.equal((await call('flags-clear', {})).cleared, 1);
    const u = spawnSync(process.execPath, [CLI, 'flags', 'bogus', '--project', dir], { encoding: 'utf8', env: process.env });
    assert.equal(u.status, 2);
    await call('discard', { id: s.id });
  } finally {
    server.close();
    up.close();
  }
});

test('the public session carries the owner words the page check looks for', async () => {
  const dir = tempSite();
  const s = await heroSession(dir, 1);
  assert.ok(s.owner.some((t) => /Sourdough delivered/.test(t)));
  assert.ok(s.owner.includes('Order your first loaf'));
  engine.discard(dir, s.id);
  assert.ok(!fs.existsSync(path.join(dir, 'components/dh-tryon')));
});

test('the sub-action may come after the options (`flags --project <dir> list`), as it may before them', async () => {
  const dir = tempSite();
  const s = await heroSession(dir);
  addFlag(dir, { session: s.id, idx: 1, reasons: ['layout'] });
  for (const args of [['flags', '--project', dir, 'list'], ['flags', 'list', '--project', dir]]) {
    const r = spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf8', env: process.env });
    assert.equal(r.status, 0, args.join(' ') + ': ' + r.stdout);
    assert.equal(JSON.parse(r.stdout).flags.length, 1);
  }
});

test('serve on a port already taken says so (an older try-on server may be showing another project)', async () => {
  const dir = tempSite();
  const busy = (await import('node:http')).createServer(() => {});
  await new Promise((r) => busy.listen(0, '127.0.0.1', r));
  try {
    const { spawn } = await import('node:child_process');
    const c = spawn(process.execPath, [CLI, 'serve', '--project', dir, '--port', String(busy.address().port), '--target', 'http://127.0.0.1:9'], { env: process.env });
    let out = '';
    c.stdout.on('data', (d) => { out += d; });
    const code = await new Promise((r) => c.on('exit', r));
    const j = JSON.parse(out.trim().split('\n').pop());
    assert.equal(code, 1);
    assert.equal(j.code, 'PORT_BUSY');
    assert.match(j.message, /--port/);
  } finally { busy.close(); }
});
