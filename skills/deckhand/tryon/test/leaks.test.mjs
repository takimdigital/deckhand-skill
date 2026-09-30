// A test run must leave nothing in the OS temp dir: mktmp() folders go when the process exits.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { HERE } from './helpers.mjs';

test('mktmp folders (and the offline() cache/library) are removed when the process exits', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'dh-test-leak-'));   // a private "OS temp dir" for the child
  try {
    const helpers = path.join(HERE, 'helpers.mjs').split(path.sep).join('/');
    const code = `import { mktmp, tempSite, offline } from 'file:///${helpers}'; const a = mktmp('dh-test-a-'); tempSite(); offline();`;
    const r = spawnSync(process.execPath, ['--input-type=module', '-e', code], { env: { ...process.env, TMPDIR: tmp, TEMP: tmp, TMP: tmp }, encoding: 'utf8' });
    assert.equal(r.status, 0, r.stderr);
    assert.deepEqual(fs.readdirSync(tmp), []);
  } finally { fs.rmSync(tmp, { recursive: true, force: true }); }
});
