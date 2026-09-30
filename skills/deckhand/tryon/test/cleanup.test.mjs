// Nothing a test creates may outlive the test run: every temp folder comes from scratch() (tryon/test/helpers.mjs), which
// removes them all when the process exits. A raw fs.mkdtempSync(os.tmpdir()) anywhere in the tests leaks a folder per run
// (one leak was 2013 site copies, gigabytes, on a developer's drive).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

test('no test creates a temp folder except through scratch()', () => {
  const bad = [];
  for (const f of fs.readdirSync(HERE).filter((x) => x.endsWith('.mjs') && x !== 'helpers.mjs' && x !== 'cleanup.test.mjs')) {
    fs.readFileSync(path.join(HERE, f), 'utf8').split('\n').forEach((l, i) => { if (/mkdtemp(Sync)?\(/.test(l)) bad.push(`${f}:${i + 1}`); });
  }
  const pg = path.resolve(HERE, '..', '..', '..', '..', 'playground');
  if (fs.existsSync(pg)) for (const f of fs.readdirSync(pg).filter((x) => x.endsWith('.test.mjs'))) {
    fs.readFileSync(path.join(pg, f), 'utf8').split('\n').forEach((l, i) => { if (/mkdtemp(Sync)?\(/.test(l) && !/scratch\(/.test(l)) bad.push(`playground/${f}:${i + 1}`); });
  }
  assert.deepEqual(bad, [], 'use scratch(prefix) from helpers.mjs');
});

test('scratch() folders are gone when the process ends, even when it fails', () => {
  const marker = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'dh-cleanup-probe-')), 'seen.txt');   // the probe's own report, removed below
  const helpers = pathToFileURL(path.join(HERE, 'helpers.mjs')).href;
  for (const fail of [false, true]) {
    const code = `import { scratch } from ${JSON.stringify(helpers)}; import fs from 'node:fs'; const d = scratch('dh-probe-'); fs.writeFileSync(d + '/x', 'x'); fs.appendFileSync(${JSON.stringify(marker)}, d + '\\n'); ${fail ? "throw new Error('boom');" : ''}`;
    spawnSync(process.execPath, ['--input-type=module', '-e', code], { encoding: 'utf8' });
  }
  const made = fs.readFileSync(marker, 'utf8').trim().split('\n');
  assert.equal(made.length, 2);
  for (const d of made) assert.ok(!fs.existsSync(d), `left behind: ${d}`);
  fs.rmSync(path.dirname(marker), { recursive: true, force: true });
});
