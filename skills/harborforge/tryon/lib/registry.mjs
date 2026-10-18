/**
 * registry.mjs — fetch a catalog item into a normalized, self-contained bundle:
 *   { files: [{ key, path, content }], entryKey, deps[], rdeps[], css, cssVars, origin, sourceUrl }
 *
 * Two transports, tried in order, both cached on disk (a click never refetches):
 *   json — a shadcn-schema registry item (`files[].content` required; content-less = refused)
 *   gh   — MIT GitHub source: fetch the entry file, then follow every `@/registry/...` and
 *          relative import recursively (bounded), collecting bare imports as npm deps.
 * Guard rails: https only (http only on loopback, for fixtures), size cap, file-count cap,
 * timeout. Offline replay: DH_FIXTURES=<dir> serves recorded responses; DH_RECORD=<dir> records.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { parse, walk } = require('./ast.cjs');

const MAX_BYTES = 1024 * 1024;
const MAX_FILES = 40;
const BUILTIN = new Set(['react', 'react-dom', 'next', 'react/jsx-runtime']);

export function cacheDir() {
  return process.env.DH_CACHE || path.join(process.env.DECKHAND_HOME || path.join(os.homedir(), '.deckhand'), 'cache', 'tryon');
}

export const keyOf = (url) => crypto.createHash('sha1').update(url).digest('hex').slice(0, 20);

export async function getText(url, { cache = true } = {}) {
  const k = keyOf(url);
  const fx = process.env.DH_FIXTURES;
  if (fx) {
    const p = path.join(fx, k + '.txt');
    if (fs.existsSync(p)) return fs.readFileSync(p, 'utf8');
    for (const code of [404, 401, 402, 403, 429, 500]) {
      if (fs.existsSync(path.join(fx, k + '.' + code))) throw Object.assign(new Error('HTTP ' + code + ' ' + url), { status: code });
    }
    if (!process.env.DH_FIXTURES_PASSTHROUGH) throw Object.assign(new Error('FIXTURE_MISSING ' + url), { status: 599 });
  }
  const cdir = cacheDir();
  const cpath = path.join(cdir, k + '.txt');
  if (cache && fs.existsSync(cpath)) return fs.readFileSync(cpath, 'utf8');

  const u = new URL(url);
  const loop = ['127.0.0.1', 'localhost', '::1', '[::1]'].includes(u.hostname);
  if (u.protocol !== 'https:' && !(u.protocol === 'http:' && loop)) {
    throw Object.assign(new Error('URL_NOT_ALLOWED ' + url), { status: 400 });
  }
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 20000);
  let res;
  try {
    res = await fetch(url, { signal: ctl.signal, headers: { 'user-agent': 'deckhand-tryon/2 (+local dev)' } });
  } finally { clearTimeout(t); }
  const rec = process.env.DH_RECORD;
  if (!res.ok) {
    if (rec) { fs.mkdirSync(rec, { recursive: true }); fs.writeFileSync(path.join(rec, k + '.404'), url); }
    throw Object.assign(new Error('HTTP ' + res.status + ' ' + url), { status: res.status });
  }
  const buf = Buffer.from(await res.arrayBuffer());
  if (buf.length > MAX_BYTES) throw Object.assign(new Error('TOO_LARGE ' + url), { status: 413 });
  const text = buf.toString('utf8');
  if (cache) { fs.mkdirSync(cdir, { recursive: true }); fs.writeFileSync(cpath, text); }
  if (rec) { fs.mkdirSync(rec, { recursive: true }); fs.writeFileSync(path.join(rec, k + '.txt'), text); }
  return text;
}

/** Module specifiers of a source file (static imports, re-exports, literal dynamic imports). */
export function importsOf(file, text) {
  const out = [];
  let ast;
  try { ast = parse(file, text); } catch { return out; }
  walk(ast, (n) => {
    if ((n.type === 'ImportDeclaration' || n.type === 'ExportNamedDeclaration' || n.type === 'ExportAllDeclaration') && n.source) {
      if (n.importKind !== 'type' && n.exportKind !== 'type') out.push({ spec: n.source.value, start: n.source.start, end: n.source.end });
      else out.push({ spec: n.source.value, start: n.source.start, end: n.source.end, typeOnly: true });
    } else if (n.type === 'CallExpression' && n.callee.type === 'Import' && n.arguments[0]?.type === 'StringLiteral') {
      out.push({ spec: n.arguments[0].value, start: n.arguments[0].start, end: n.arguments[0].end });
    }
    return true;
  });
  return out;
}

/** "motion/react" -> "motion"; "@radix-ui/react-slot/x" -> "@radix-ui/react-slot". */
export function pkgName(spec) {
  const parts = spec.split('/');
  return spec.startsWith('@') ? parts.slice(0, 2).join('/') : parts[0];
}

const isBare = (s) => !s.startsWith('.') && !s.startsWith('/') && !/^[@~#]\//.test(s) && !s.startsWith('@/');
const isNodeBuiltin = (s) => s.startsWith('node:') || ['fs', 'path', 'os', 'crypto', 'url', 'util', 'stream'].includes(s);

/**
 * Follow a GitHub source graph. `stop(spec)` returns a truthy value for imports the caller will
 * satisfy itself (e.g. a ui primitive the project already has) — those are recorded, not fetched.
 */
export async function followGh({ repo, entryPath, importRoots = { '@/registry/': 'registry/' }, stop = () => null }) {
  const raw = (p) => `https://raw.githubusercontent.com/${repo}/${p}`;
  const files = new Map();            // repo path -> content
  const deps = new Set();
  const external = new Map();         // spec -> stop() verdict
  const unresolved = [];
  const queue = [entryPath];

  async function resolveRepoPath(base) {
    if (/\.(tsx|ts|jsx|js|css)$/.test(base)) {
      try { return [base, await getText(raw(base))]; } catch { /* fallthrough */ }
    }
    for (const cand of [base + '.tsx', base + '.ts', base + '.jsx', base + '.js', base + '/index.tsx', base + '/index.ts']) {
      try { return [cand, await getText(raw(cand))]; } catch (e) { if (e.status && e.status !== 404 && e.status !== 599) throw e; }
    }
    return [null, null];
  }

  while (queue.length) {
    const p = queue.shift();
    if (files.has(p)) continue;
    if (files.size >= MAX_FILES) throw Object.assign(new Error('TOO_MANY_FILES'), { code: 'TOO_MANY_FILES' });
    const [real, text] = files.size === 0 ? await resolveRepoPath(p) : await resolveRepoPath(p);
    if (!real) { unresolved.push(p); continue; }
    files.set(real, text);
    for (const imp of importsOf(real, text)) {
      const s = imp.spec;
      if (isNodeBuiltin(s)) continue;
      const verdict = stop(s);
      if (verdict) { external.set(s, verdict); continue; }
      const root = Object.keys(importRoots).find((r) => s.startsWith(r));
      if (root) { queue.push(importRoots[root] + s.slice(root.length)); continue; }
      if (s.startsWith('.')) { queue.push(path.posix.normalize(path.posix.join(path.posix.dirname(real), s))); continue; }
      if (s.startsWith('@/')) { unresolved.push(s); continue; }
      if (isBare(s) && !imp.typeOnly) { const n = pkgName(s); if (!BUILTIN.has(n) && !BUILTIN.has(s)) deps.add(n); }
    }
  }
  const [entryReal] = [...files.keys()];
  return { files, entry: entryReal, deps: [...deps], external: Object.fromEntries(external), unresolved };
}

/** Fetch a shadcn-schema JSON item. */
export async function fetchJsonItem(url) {
  const doc = JSON.parse(await getText(url));
  const files = (doc.files || []).filter((f) => typeof f.content === 'string' && f.content.length);
  if (!files.length) throw Object.assign(new Error('CONTENT_LESS_ITEM ' + url), { code: 'CONTENT_LESS_ITEM' });
  return doc;
}
