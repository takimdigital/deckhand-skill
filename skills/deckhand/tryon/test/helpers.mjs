import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const HERE = path.dirname(fileURLToPath(import.meta.url));

/**
 * Every temp folder a test makes lives under ONE root per process, removed when the process ends (normal exit, a failed
 * assertion, an uncaught error, Ctrl-C). A raw mkdtempSync leaks a folder per call, per run: a site copy is hundreds of MB.
 */
let SCRATCH = null;
const wipe = () => { if (SCRATCH) { try { fs.rmSync(SCRATCH, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 }); } catch { /* best effort */ } SCRATCH = null; } };
export function scratch(prefix = 'dh-') {
  if (!SCRATCH) {
    SCRATCH = fs.mkdtempSync(path.join(os.tmpdir(), 'dh-test-'));
    process.on('exit', wipe);
    for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { wipe(); process.exit(1); });
  }
  return fs.mkdtempSync(path.join(SCRATCH, prefix));
}
export const FIXTURE_SITE = path.join(HERE, 'fixtures', 'site');
export const FIXTURE_REGISTRY = path.join(HERE, 'fixtures', 'registry');

/** A throwaway copy of the fixture site with stub node_modules (deps "installed"). */
export function tempSite(extraDeps = []) {
  const dir = scratch('dh-tryon-');
  fs.cpSync(FIXTURE_SITE, dir, { recursive: true });
  const pkg = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8'));
  const deps = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies }).concat(['motion', 'react-use-measure'], extraDeps);
  for (const d of deps) {
    fs.mkdirSync(path.join(dir, 'node_modules', d), { recursive: true });
    fs.writeFileSync(path.join(dir, 'node_modules', d, 'package.json'), JSON.stringify({ name: d, version: '0.0.0' }));
  }
  return dir;
}

/** Offline, deterministic registry + an empty personal library. */
export function offline() {
  process.env.DH_FIXTURES = FIXTURE_REGISTRY;
  process.env.DH_CACHE = scratch('dh-cache-');
  process.env.DECKHAND_LIBRARY = scratch('dh-lib-');
}

export const read = (dir, f) => fs.readFileSync(path.join(dir, f), 'utf8');

/** 1-based line/col of the first occurrence of `needle` (col of its first char). */
export function locate(text, needle) {
  const i = text.indexOf(needle);
  if (i < 0) throw new Error('not found: ' + needle);
  const before = text.slice(0, i);
  const line = before.split('\n').length;
  return { line, col: i - before.lastIndexOf('\n') };
}
