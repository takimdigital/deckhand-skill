import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { tempSite, offline, read } from './helpers.mjs';
import { setup, unsetup, patchNextConfig, patchViteConfig } from '../lib/setup.mjs';
import { normalizeClassList, normalizeClasses, tokenLayer, stripTokenLayer } from '../lib/theme.mjs';
import { startServer } from '../server.mjs';

const require = createRequire(import.meta.url);
const { parse } = require('../lib/ast.cjs');
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');
offline();

test('palette classes become the site tokens; dark twins drop; hover keeps intent', () => {
  assert.equal(normalizeClassList('bg-zinc-50 dark:bg-zinc-900 text-gray-500'), 'bg-muted text-muted-foreground');
  assert.equal(normalizeClassList('bg-indigo-600 hover:bg-indigo-700 text-white'), 'bg-primary hover:bg-primary/90 text-primary-foreground');
  assert.equal(normalizeClassList('border-slate-200/60 ring-blue-500'), 'border-border/60 ring-primary');
  assert.equal(normalizeClassList('bg-emerald-500 text-red-600'), 'bg-emerald-500 text-red-600');   // status colours stay
  const out = normalizeClasses('x.tsx', 'const a = <div className={cn("bg-white", ok && "text-zinc-900")} title="bg-zinc-50" />;');
  assert.match(out.code, /cn\("bg-background", ok && "text-foreground"\)/);
  assert.match(out.code, /title="bg-zinc-50"/);                                           // not a class list
});

test('token layer: only missing tokens, derived from the site colours; strip restores the stylesheet', () => {
  const css = '@import "tailwindcss";\n:root { --background: #fff; --foreground: #111; }\n';
  const layer = tokenLayer(css, { primary: 'rgb(217, 119, 6)' });
  assert.doesNotMatch(layer, /--background:/);
  assert.match(layer, /--primary: rgb\(217, 119, 6\);/);
  assert.match(layer, /--muted-foreground: color-mix\(in oklab, var\(--foreground\) 62%, var\(--background\)\);/);
  assert.match(layer, /--color-primary: var\(--primary\);/);
  const withLayer = css.replace(/\s*$/, '\n') + layer;
  assert.equal(stripTokenLayer(withLayer), css);
  assert.equal(tokenLayer(withLayer + ':root{--primary:x;--primary-foreground:x;--secondary:x;--secondary-foreground:x;--muted:x;--muted-foreground:x;--accent:x;--accent-foreground:x;--destructive:x;--border:x;--input:x;--ring:x;--card:x;--card-foreground:x;--popover:x;--popover-foreground:x;--radius:1px}'), '');
});

test('next.config is wrapped once (ts, mjs, cjs, function config) and still parses', () => {
  const ts = patchNextConfig('next.config.ts', 'import type { NextConfig } from "next";\nconst c: NextConfig = {};\nexport default c;\n');
  assert.match(ts.code, /export default withDeckhandTryon\(c\);/);
  assert.match(ts.code, /import \{ withDeckhandTryon \} from "\.\/\.deckhand\/tryon\/runtime\/next-plugin\.cjs"; \/\/ deckhand-tryon/);
  assert.equal(patchNextConfig('next.config.ts', ts.code).changed, false);
  const cjs = patchNextConfig('next.config.js', 'module.exports = { reactStrictMode: true };\n');
  assert.match(cjs.code, /module\.exports = withDeckhandTryon\(\{ reactStrictMode: true \}\);/);
  assert.match(cjs.code, /require\("\.\/\.deckhand\/tryon\/runtime\/next-plugin\.cjs"\)/);
  const fn = patchNextConfig('next.config.mjs', 'export default (phase) => ({ output: "standalone" });\n');
  parse('n.mjs', fn.code);
  const vite = patchViteConfig('vite.config.ts', 'import react from "@vitejs/plugin-react";\nexport default { plugins: [react()] };\n');
  assert.match(vite.code, /plugins: \[dhTryon\(\), react\(\)\]/);
});

test('unsetup takes back the .gitignore lines setup added: byte-exact, CRLF too, and a file it created goes', () => {
  const dir = tempSite();
  assert.ok(!fs.existsSync(path.join(dir, '.gitignore')));
  setup(dir);
  unsetup(dir);
  assert.ok(!fs.existsSync(path.join(dir, '.gitignore')), 'setup created it: clean removes it');
  const own = 'node_modules/\r\n.next/\r\n';
  fs.writeFileSync(path.join(dir, '.gitignore'), own);
  setup(dir);
  // an editor on Windows rewrites the whole file with CRLF
  fs.writeFileSync(path.join(dir, '.gitignore'), read(dir, '.gitignore').replace(/\r?\n/g, '\r\n'));
  unsetup(dir);
  assert.equal(read(dir, '.gitignore'), own);
});

test('setup -> unsetup is byte-exact and gitignores the state dir', () => {
  const dir = tempSite();
  const cfg = fs.readFileSync(path.join(dir, 'next.config.ts'));
  const r = setup(dir);
  assert.equal(r.patched, true);
  assert.ok(fs.existsSync(path.join(dir, '.deckhand/tryon/runtime/loader.cjs')));
  assert.match(read(dir, '.gitignore'), /^\.deckhand\/tryon\/$/m);
  // the runtime plugin is inert outside development and wires Turbopack without `as` in dev
  const plugin = require(path.join(dir, '.deckhand/tryon/runtime/next-plugin.cjs'));
  const prev = process.env.NODE_ENV;
  process.env.NODE_ENV = 'production';
  assert.deepEqual(plugin.withDeckhandTryon({ a: 1 }), { a: 1 });
  process.env.NODE_ENV = 'development';
  const dev = plugin.withDeckhandTryon({ turbopack: { rules: { '*.svg': { loaders: ['svgr'], as: '*.js' } } } });
  assert.ok(dev.turbopack.rules['*.svg'] && dev.turbopack.rules['*.tsx']);
  assert.equal(dev.turbopack.rules['*.tsx'].as, undefined);
  process.env.NODE_ENV = prev;
  unsetup(dir, { keepTokens: false });
  assert.equal(sha(fs.readFileSync(path.join(dir, 'next.config.ts'))), sha(cfg));
  assert.ok(!fs.existsSync(path.join(dir, '.deckhand/tryon/runtime')));
});

test('the loader stamps only in development and only project source', () => {
  const loader = require('../loader.cjs');
  const ctx = (file) => ({ resourcePath: file, rootContext: '/p', getOptions: () => ({ root: '/p' }) });
  const prev = process.env.NODE_ENV;
  process.env.NODE_ENV = 'production';
  assert.equal(loader.call(ctx('/p/app/page.tsx'), '<p>x</p>'), '<p>x</p>');
  process.env.NODE_ENV = 'development';
  assert.match(loader.call(ctx('/p/app/page.tsx'), 'const a = <p>x</p>;'), /data-dh="app\/page\.tsx:1:11"/);
  assert.equal(loader.call(ctx('/p/node_modules/x/a.tsx'), 'const a = <p>x</p>;'), 'const a = <p>x</p>;');
  assert.equal(loader.call(ctx('/elsewhere/a.tsx'), 'const a = <p>x</p>;'), 'const a = <p>x</p>;');
  process.env.NODE_ENV = prev;
});

test('proxy injects the overlay into HTML, passes assets through, and gates the API by token', async () => {
  const dir = tempSite();
  const up = http.createServer((req, res) => {
    if (req.url === '/') { res.writeHead(200, { 'content-type': 'text/html', 'content-security-policy': "script-src 'none'" }); res.write('<!doctype html><html><he'); res.end('ad><title>x</title></head><body>hi</body></html>'); return; }
    res.writeHead(200, { 'content-type': 'application/javascript', 'x-host': req.headers.host });
    res.end('console.log(1)');
  });
  await new Promise((r) => up.listen(0, '127.0.0.1', r));
  const target = `http://127.0.0.1:${up.address().port}`;
  const { server, url, token } = await startServer({ root: dir, port: 0, target });
  try {
    const html = await (await fetch(url + '/')).text();
    assert.match(html, /<head><script src="\/__dh\/overlay\.js" data-dh-token="[0-9a-f]{32}" defer><\/script><title>/);
    const r = await fetch(url + '/app.js');
    assert.equal(await r.text(), 'console.log(1)');
    assert.equal(r.headers.get('x-host'), `localhost:${up.address().port}`);    // Next allows localhost by default
    const denied = await fetch(url + '/__dh/api/state');
    assert.equal(denied.status, 403);
    const st = await (await fetch(url + '/__dh/api/state', { headers: { 'x-dh-token': token } })).json();
    assert.equal(st.ok, true);
    assert.ok(st.slots.hero > 0);
    const ov = await (await fetch(url + '/__dh/overlay.js')).text();
    assert.match(ov, /__DH_TRYON__/);
  } finally {
    server.close();
    up.close();
  }
});
