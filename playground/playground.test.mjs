// Playground smoke: restore the site, start the dev server, and prove the home page and the kitchen sink both render (HTTP 200,
// no React error page). Slow (installs dependencies on first run), so it is opt-in:  DH_PLAYGROUND=1 node --test playground/playground.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import net from 'node:net';
import { spawn, spawnSync } from 'node:child_process';
import { restore, kitchen, snapshot } from './playground.mjs';
import { scratch } from '../skills/deckhand/tryon/test/helpers.mjs';

const get = (url) => new Promise((res) => { http.get(url, (r) => { let b = ''; r.on('data', (d) => (b += d)); r.on('end', () => res({ status: r.statusCode, body: b })); }).on('error', () => res({ status: 0, body: '' })); });
const freePort = () => new Promise((res) => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });

test('the snapshot is source only and every section imports what its file exports', () => {
  const site = path.join(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')), 'tryon-site');
  assert.ok(fs.existsSync(path.join(site, 'package.json')));
  for (const gone of ['node_modules', '.next', '.git', '.env', 'components/dh-tryon', 'app/page.tsx.before-compose']) assert.ok(!fs.existsSync(path.join(site, gone)), gone);
  const page = fs.readFileSync(path.join(site, 'app', 'page.tsx'), 'utf8');
  for (const m of page.matchAll(/import (?:(\w+)|\{ (\w+) as (\w+) \}) from "@\/([^"]+)"/g)) {
    const file = path.join(site, m[4] + '.tsx');
    assert.ok(fs.existsSync(file), m[4]);
    const src = fs.readFileSync(file, 'utf8');
    if (m[1]) assert.match(src, /export default/, `${m[4]} has no default export`);
    else assert.match(src, new RegExp(`export (function|const) ${m[2]}\\b|export \\{[^}]*\\b${m[2]}\\b`), `${m[4]} does not export ${m[2]}`);
  }
  const all = JSON.stringify([...fs.readdirSync(site)]) + fs.readFileSync(path.join(site, '.deckhand', 'brief.json'), 'utf8');
  assert.ok(!/C:\\|AppData|Users\\/.test(all));
});

test('DH_PLAYGROUND: restore, dev server, / and /kitchen-sink answer 200 with no React error', { skip: !process.env.DH_PLAYGROUND, timeout: 600000 }, async () => {
  const dir = scratch('dh-playground-');                      // removed when the process ends, whatever happens
  const r = await restore(dir);
  assert.ok(r.kitchen >= 40, 'a kitchen-sink block for every slot kind');
  const port = await freePort();
  const dev = spawn('npm', ['run', 'dev', '--', '--port', String(port)], { cwd: dir, shell: process.platform === 'win32', stdio: 'ignore', windowsHide: true });
  try {
    let home = { status: 0 };
    for (let i = 0; i < 120 && home.status !== 200; i++) { home = await get(`http://127.0.0.1:${port}/`); if (home.status !== 200) await new Promise((x) => setTimeout(x, 1000)); }
    assert.equal(home.status, 200);
    assert.ok(!/Element type is invalid/.test(home.body), 'home renders every section');
    const sink = await get(`http://127.0.0.1:${port}/kitchen-sink`);
    assert.equal(sink.status, 200);
    assert.ok(!/Element type is invalid|Unhandled Runtime Error/.test(sink.body));
    assert.match(sink.body, /Try-on kitchen sink/);
    for (const slot of ['tabs', 'dialog', 'table', 'sidebar', 'chart', 'calendar']) assert.match(sink.body, new RegExp(`id="slot-${slot}"`), slot);
  } finally {
    if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(dev.pid), '/T', '/F']); else dev.kill('SIGTERM');
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
