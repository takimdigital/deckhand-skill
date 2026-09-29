// Regressions from the 2026-09-29 final audit (try-on area): each test is one finding, reproduced, and now impossible.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { tempSite, offline } from './helpers.mjs';
import * as engine from '../lib/engine.mjs';
import { startServer, localHost } from '../server.mjs';
import { themeApply, themeUndo } from '../lib/sitetheme.mjs';

offline();
const COMPOSE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'compose.mjs');

const get = (port, host, p = '/__dh/api/state', headers = {}) => new Promise((resolve, reject) => {
  const req = http.request({ host: '127.0.0.1', port, path: p, headers: { host, ...headers } }, (res) => {
    let body = ''; res.on('data', (c) => { body += c; }); res.on('end', () => resolve({ status: res.statusCode, body }));
  });
  req.on('error', reject); req.end();
});

test('Y4: a request naming another host (DNS rebinding) gets neither the page nor the API', async () => {
  const dir = tempSite();
  const up = http.createServer((req, res) => { res.writeHead(200, { 'content-type': 'text/html' }); res.end('<html><head></head><body>hi</body></html>'); });
  await new Promise((r) => up.listen(0, '127.0.0.1', r));
  const { server, token } = await startServer({ root: dir, port: 0, target: `http://127.0.0.1:${up.address().port}` });
  const port = server.address().port;
  try {
    for (const p of ['/', '/__dh/api/state']) {
      const r = await get(port, `attacker.example:${port}`, p, { 'x-dh-token': token });
      assert.equal(r.status, 403, p);
      assert.doesNotMatch(r.body, new RegExp(token));
    }
    assert.equal((await get(port, `127.0.0.1:${port}`, '/')).status, 200);
    assert.equal((await get(port, `localhost:${port}`, '/')).status, 200);
  } finally { server.close(); up.close(); }
  for (const h of ['127.0.0.1:3999', 'localhost:3999', '[::1]:3999', '192.168.1.20:3999']) assert.ok(localHost(h), h);
  for (const h of ['attacker.example:3999', 'localhost.attacker.example', '', undefined]) assert.ok(!localHost(h), String(h));
});

test('Y5: inspect refuses a file outside the project', () => {
  const dir = tempSite();
  fs.writeFileSync(path.join(dir, '..', 'outside.tsx'), 'export const a = <p>OUTSIDE-SECRET</p>;\n');
  assert.throws(() => engine.inspect(dir, { file: '../outside.tsx', line: 1, col: 18 }), (e) => e.code === 'OUTSIDE_PROJECT');
});

test('Y7: a malformed copy.json is a readable refusal, not a stack trace, and the page is untouched', () => {
  const dir = tempSite();
  fs.writeFileSync(path.join(dir, 'copy.json'), '{"hero": {"heading": "x"},}');
  const page = path.join(dir, 'app', 'page.tsx');
  const before = fs.existsSync(page) ? fs.readFileSync(page, 'utf8') : null;
  const r = spawnSync(process.execPath, [COMPOSE, '--project', dir, '--copy', 'copy.json'], { encoding: 'utf8' });
  assert.equal(r.status, 1);
  const out = JSON.parse(r.stdout.trim().split('\n').pop());
  assert.equal(out.code, 'BAD_COPY');
  assert.doesNotMatch(r.stderr, /at .*compose\.mjs/);
  assert.equal(fs.existsSync(page) ? fs.readFileSync(page, 'utf8') : null, before);
});

test('Y1: a compose that places nothing leaves the page and its first backup alone', () => {
  const dir = tempSite();
  const page = path.join(dir, 'app', 'page.tsx');
  fs.mkdirSync(path.dirname(page), { recursive: true });
  fs.writeFileSync(page, 'export default function Page(){ return <main>OWNER</main> }\n');
  fs.writeFileSync(page + '.before-compose', 'ORIGINAL\n');
  const r = spawnSync(process.execPath, [COMPOSE, '--project', dir, '--sections', 'nosuchslot'], { encoding: 'utf8', env: { ...process.env } });
  const out = JSON.parse(r.stdout.trim().split('\n').pop());
  assert.equal(out.ok, false);
  assert.match(fs.readFileSync(page, 'utf8'), /OWNER/);
  assert.equal(fs.readFileSync(page + '.before-compose', 'utf8'), 'ORIGINAL\n');
});

test('Y2: a second compose never clears a section folder another page (or the owner) uses', () => {
  const dir = tempSite();
  const run = (page) => spawnSync(process.execPath, [COMPOSE, '--project', dir, '--sections', 'hero', '--page', page, '--install', 'no', '--tries', '2'], { encoding: 'utf8', env: process.env });
  const first = JSON.parse(run('app/page.tsx').stdout.trim().split('\n').pop());
  assert.equal(first.ok, true, JSON.stringify(first));
  const entry = path.join(dir, first.sections[0].component);
  fs.appendFileSync(entry, '\n// OWNER EDIT\n');
  const second = JSON.parse(run('app/y/page.tsx').stdout.trim().split('\n').pop());
  assert.equal(second.ok, true);
  assert.notEqual(second.sections[0].component, first.sections[0].component);
  assert.match(fs.readFileSync(entry, 'utf8'), /OWNER EDIT/);
  assert.ok(fs.existsSync(path.join(dir, second.sections[0].component)));
  assert.deepEqual(fs.readdirSync(path.join(dir, 'components', 'sections')).filter((f) => f.startsWith('.dh-stage')), []);
});

test('Y6: theme --undo refuses to throw away an edit made after the apply, unless forced', () => {
  const dir = tempSite();
  const css = path.join(dir, fs.existsSync(path.join(dir, 'app', 'globals.css')) ? 'app/globals.css' : 'styles/globals.css');
  themeApply(dir, { accent: 'teal' });
  fs.appendFileSync(css, '\n.owner-rule { color: red }\n');
  assert.throws(() => themeUndo(dir), (e) => e.code === 'FILE_CHANGED');
  assert.match(fs.readFileSync(css, 'utf8'), /owner-rule/);
  themeUndo(dir, { force: true });
  assert.doesNotMatch(fs.readFileSync(css, 'utf8'), /owner-rule/);
  themeApply(dir, { accent: 'teal' });
  assert.equal(themeUndo(dir).mode, 'byte-exact');             // untouched since: undoes as before
});

test('A7: a refused registry is refused by name from a mirror too, and the repo must be the one serving the index', async () => {
  const { refusedFor, repoInUrl } = await import('../lib/vet.mjs');
  assert.equal(refusedFor('https://raw.githubusercontent.com/someone/shadcn-studio/main/public/r/registry.json', 'shadcn-ui/ui').id, 'shadcn-studio');
  assert.equal(refusedFor('https://mirror.example/r/registry.json', 'someone/animate-ui').id, 'animate-ui');
  assert.equal(refusedFor('https://shadcnstudio.com/r/registry.json').id, 'shadcn-studio');
  assert.equal(refusedFor('https://raw.githubusercontent.com/tailark/tailark-oss/main/r/registry.json', 'tailark/tailark-oss'), undefined);
  assert.equal(repoInUrl('https://raw.githubusercontent.com/a/b/main/registry.json'), 'a/b');
  assert.equal(repoInUrl('https://cdn.jsdelivr.net/gh/a/b@main/registry.json'), 'a/b');
  assert.equal(repoInUrl('https://ui.example/registry.json'), null);
});
