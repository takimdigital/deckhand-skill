import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const HERE = path.dirname(fileURLToPath(import.meta.url));
export const FIXTURE_SITE = path.join(HERE, 'fixtures', 'site');
export const FIXTURE_REGISTRY = path.join(HERE, 'fixtures', 'registry');

const MADE = [];
/** A temp folder that is removed when this test process exits, pass or fail (nothing is left in the OS temp dir). */
export function mktmp(prefix) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  MADE.push(dir);
  return dir;
}
process.on('exit', () => { for (const d of MADE) { try { fs.rmSync(d, { recursive: true, force: true, maxRetries: 3 }); } catch { /* clean will get it */ } } });

/** A throwaway copy of the fixture site with stub node_modules (deps "installed"). */
export function tempSite(extraDeps = []) {
  const dir = mktmp('dh-tryon-');
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
  process.env.DH_CACHE = mktmp('dh-cache-');
  process.env.DECKHAND_LIBRARY = mktmp('dh-lib-');
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
