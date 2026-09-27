/**
 * server.mjs — the try-on helper. ONE local process, no agent polling, no LLM per click:
 *
 *   http://127.0.0.1:<port>  ->  reverse proxy of the dev server (HMR websockets included)
 *                                with the overlay injected into every HTML page;
 *   /__dh/overlay.js           the picker UI;
 *   /__dh/api/*                inspect · open · show · keep · discard · more · save · state · draft ·
 *                              draft-status · tune-* · theme-* (token-gated; the engine does every write).
 *
 * AI drafts: the owner's request is written to .deckhand/tryon/drafts/ and printed on stdout as ONE
 * JSON line ({"event":"draft_request",…}) for an agent watching this process; the overlay polls only
 * the local draft-status endpoint (no model involved) until the agent's gated draft appears.
 *
 * Security: binds loopback only; API calls need the per-run token header (a cross-site page can
 * neither read it nor send the custom header without a CORS preflight, which is never granted).
 */
import http from 'node:http';
import net from 'node:net';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import * as engine from './lib/engine.mjs';
import { detectProject } from './lib/project.mjs';
import { loadCatalog, slotsSummary } from './lib/catalog.mjs';
import { saveToLibrary } from './lib/library.mjs';
import * as draft from './lib/draft.mjs';
import { tuneOpen, tuneSet, tuneKeep, tuneReset } from './lib/tune.mjs';
import { themeState, themeVars, themeApply, themeUndo } from './lib/sitetheme.mjs';
import { BLOCK_SLOTS, UI_SLOTS, EFFECT_SLOTS } from './lib/slots.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));

async function probe(url) {
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 1500);
    const r = await fetch(url, { signal: ctl.signal, redirect: 'manual' });
    clearTimeout(t);
    return r.status > 0;
  } catch { return false; }
}

export async function detectTarget(root) {
  // the dev server `dh dev start` recorded (any port) first
  try {
    const u = JSON.parse(fs.readFileSync(path.join(root, '.deckhand', 'dev.json'), 'utf8')).url;
    if (u && /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/?$/.test(u) && await probe(u.replace(/\/$/, '') + '/')) return u.replace(/\/$/, '').replace('localhost', '127.0.0.1');
  } catch { /* none recorded */ }
  const pkg = (() => { try { return JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')); } catch { return {}; } })();
  const dev = String(pkg.scripts?.dev || '');
  const m = /(?:-p|--port)[ =](\d+)/.exec(dev);
  const ports = [...new Set([m ? Number(m[1]) : null, 3000, 3001, 3002, 5173, 5174, 4321, 8080].filter(Boolean))];
  for (const p of ports) if (await probe(`http://127.0.0.1:${p}/`)) return `http://127.0.0.1:${p}`;
  return null;
}

function readBody(req, limit = 1 << 20) {
  return new Promise((resolve, reject) => {
    let n = 0; const chunks = [];
    req.on('data', (c) => { n += c.length; if (n > limit) { reject(new Error('BODY_TOO_LARGE')); req.destroy(); } else chunks.push(c); });
    req.on('end', () => { try { resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {}); } catch (e) { reject(e); } });
    req.on('error', reject);
  });
}

export function startServer({ root: rootIn, port = 3999, target, host = '127.0.0.1', log = () => {}, onDraft = () => {} }) {
  const root = path.resolve(rootIn);
  const token = crypto.randomBytes(16).toString('hex');
  const upstream = new URL(target);
  // what the dev server sees as Host/Origin: `localhost` is allowed by Next's dev-origin guard by
  // default, `127.0.0.1` is not (HMR + dev resources get blocked — measured on Next 16.3.6)
  const upHost = (upstream.hostname === '127.0.0.1' ? 'localhost' : upstream.hostname) + (upstream.port ? ':' + upstream.port : '');
  const upOrigin = upstream.protocol + '//' + upHost;
  const events = new Set();                   // SSE clients
  let queue = Promise.resolve();             // one write at a time
  const serial = (fn) => { const p = queue.then(fn, fn); queue = p.catch(() => {}); return p; };
  const emit = (ev) => { const line = `data: ${JSON.stringify(ev)}\n\n`; for (const r of events) r.write(line); };

  const overlaySrc = () => fs.readFileSync(path.join(HERE, 'overlay.js'), 'utf8');
  const tag = `<script src="/__dh/overlay.js" data-dh-token="${token}" defer></script>`;

  async function api(name, body) {
    switch (name) {
      case 'state': {
        const prof = detectProject(root);
        return { project: path.basename(root), framework: prof.framework, base: prof.base, tailwind: prof.tailwind,
          tokens: prof.tokens.primary, slots: slotsSummary(loadCatalog(), prof), allSlots: [...BLOCK_SLOTS, ...UI_SLOTS, ...EFFECT_SLOTS],
          drafts: draft.listDrafts(root, { state: ['pending', 'rejected'] }).map(draft.publicDraft),
          open: engine.listSessions(root).filter((s) => s.state === 'open').map(engine.publicSession) };
      }
      case 'inspect': return engine.inspect(root, body);
      case 'open': return serial(() => engine.openVerified(root, { ...body, onProgress: (p) => emit({ type: 'progress', ...p }) }, { url: upstream.origin, page: body.page }));
      case 'show': return serial(() => engine.show(root, body.id, body.idx));
      case 'keep': return serial(() => engine.keep(root, body.id, body.idx));
      case 'discard': return serial(() => engine.discard(root, body.id));
      // the next batch from the pool: the variants on screen stay, new ones are added after them
      case 'more': return serial(() => engine.more(root, body.id, { batch: body.batch || body.count, probe: body.probe, onProgress: (p) => emit({ type: 'progress', ...p }),
        url: upstream.origin, page: body.page }));
      case 'save': return serial(() => saveToLibrary(root, body.id, { name: body.name }));
      case 'draft': {
        // the owner asks for an AI variant: one request for the agent (it is not in the click loop)
        const r = draft.requestDraft(root, body);
        onDraft(r);
        return r;
      }
      // Tune: knobs on one element (exact class transforms, written once per change, HMR shows them)
      case 'tune-open': return tuneOpen(root, body);
      case 'tune-set': return serial(() => tuneSet(root, body.id, { dials: body.dials || {}, preset: body.preset || null }));
      case 'tune-keep': return serial(() => tuneKeep(root, body.id));
      case 'tune-reset': return serial(() => tuneReset(root, body.id));
      // Site: the whole look (CSS variables previewed with the exact values apply writes; fonts via next/font)
      case 'theme-state': return themeState(root);
      case 'theme-vars': return themeVars(body || {});
      case 'theme-apply': return serial(() => themeApply(root, body || {}));
      case 'theme-undo': return serial(() => themeUndo(root));
      case 'draft-status': {
        const d = draft.loadDraft(root, body.id);
        let session = null;
        if (d.state === 'done' && d.session) {
          try { const s = engine.loadSession(root, d.session); if (s.state === 'open') session = engine.publicSession(s); } catch { /* closed */ }
        }
        return { draft: draft.publicDraft(d), session };
      }
      default: throw Object.assign(new Error('NO_SUCH_API ' + name), { code: 'NO_SUCH_API', status: 404 });
    }
  }

  function proxy(req, res) {
    const headers = { ...req.headers, host: upHost, 'accept-encoding': 'identity' };
    if (headers.origin) headers.origin = upOrigin;
    if (headers.referer) headers.referer = headers.referer.replace(/^https?:\/\/[^/]+/, upOrigin);
    const up = http.request({ hostname: upstream.hostname, port: upstream.port, path: req.url, method: req.method, headers }, (ur) => {
      const h = { ...ur.headers };
      const html = /text\/html/i.test(String(h['content-type'] || '')) && req.method === 'GET';
      if (!html) { res.writeHead(ur.statusCode, h); ur.pipe(res); return; }
      delete h['content-length'];
      delete h['content-security-policy'];
      delete h['content-security-policy-report-only'];
      res.writeHead(ur.statusCode, h);
      let injected = false, buf = '';
      ur.setEncoding('utf8');
      ur.on('data', (chunk) => {
        if (injected) { res.write(chunk); return; }
        buf += chunk;
        const m = /<head(\s[^>]*)?>/i.exec(buf);
        if (m) {
          const at = m.index + m[0].length;
          res.write(buf.slice(0, at) + tag + buf.slice(at));
          injected = true; buf = '';
        } else if (buf.length > 256 * 1024) { res.write(buf); injected = true; buf = ''; }
      });
      ur.on('end', () => { if (buf) res.write(injected ? buf : buf + tag); res.end(); });
    });
    up.on('error', (e) => { res.writeHead(502, { 'content-type': 'text/plain' }); res.end('deckhand try-on: dev server unreachable at ' + upstream.origin + ' — ' + e.message); });
    req.pipe(up);
  }

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://x');
    if (url.pathname === '/__dh/overlay.js') {
      res.writeHead(200, { 'content-type': 'application/javascript; charset=utf-8', 'cache-control': 'no-store' });
      res.end(overlaySrc());
      return;
    }
    if (url.pathname === '/__dh/events') {
      if (url.searchParams.get('t') !== token) { res.writeHead(403); res.end(); return; }
      res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store', connection: 'keep-alive' });
      res.write(': ok\n\n');
      events.add(res);
      req.on('close', () => events.delete(res));
      return;
    }
    if (url.pathname.startsWith('/__dh/api/')) {
      if (req.headers['x-dh-token'] !== token) { res.writeHead(403, { 'content-type': 'application/json' }); res.end('{"ok":false,"code":"BAD_TOKEN"}'); return; }
      const name = url.pathname.slice('/__dh/api/'.length);
      try {
        const body = req.method === 'POST' ? await readBody(req) : {};
        const out = await api(name, body);
        log({ api: name, ok: true });
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ ok: true, ...out }));
      } catch (e) {
        log({ api: name, ok: false, code: e.code, message: e.message });
        // a typed refusal (NO_VARIANTS, ELEMENT_NOT_FOUND…) is an answer the overlay shows, not a failed request
        // (a 400 would print "Failed to load resource" in the owner's console); a crash stays a 500
        const bad = e instanceof SyntaxError || /BODY_TOO_LARGE/.test(String(e.message));   // the request itself is malformed
        res.writeHead(e.status || (bad ? 400 : e.code ? 200 : 500), { 'content-type': 'application/json' });
        res.end(JSON.stringify({ ok: false, code: e.code || 'ERROR', message: String(e.message).slice(0, 2000), skipped: e.skipped, problems: e.problems, draft: e.draft,
          reload: e.reload, restored: e.restored, dropped: e.dropped, installedKept: e.installedKept, pool: e.pool, max: e.max }));
      }
      return;
    }
    proxy(req, res);
  });

  // HMR / websocket passthrough
  server.on('upgrade', (req, sock, head) => {
    const up = net.connect(Number(upstream.port) || 80, upstream.hostname, () => {
      const lines = [`${req.method} ${req.url} HTTP/1.1`];
      for (const [k, v] of Object.entries(req.headers)) lines.push(`${k}: ${k === 'host' ? upHost : (k === 'origin' ? upOrigin : v)}`);
      up.write(lines.join('\r\n') + '\r\n\r\n');
      if (head && head.length) up.write(head);
      sock.pipe(up).pipe(sock);
    });
    up.on('error', () => sock.destroy());
    sock.on('error', () => up.destroy());
  });

  return new Promise((resolve, reject) => {
    server.on('error', reject);
    server.listen(port, host, () => resolve({ server, token, url: `http://${host === '0.0.0.0' ? '127.0.0.1' : host}:${server.address().port}`, target }));
  });
}
