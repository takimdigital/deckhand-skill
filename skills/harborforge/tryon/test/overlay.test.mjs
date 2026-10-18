// The overlay runs in the owner's browser (verified live in Chromium; the harness is not a dependency). Offline,
// these pins keep what the live runs proved: it parses as a plain script, and the behaviours that broke once stay fixed.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const SRC = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'overlay.js'), 'utf8');
const fnBody = (name) => {
  const i = SRC.indexOf('function ' + name + '(');
  assert.ok(i >= 0, 'function ' + name);
  let depth = 0;
  for (let j = SRC.indexOf('{', i); j < SRC.length; j++) {
    if (SRC[j] === '{') depth++;
    else if (SRC[j] === '}' && --depth === 0) return SRC.slice(i, j + 1);
  }
  return '';
};

test('the overlay is one plain script (no modules, no build step) that any browser runs', () => {
  assert.doesNotThrow(() => new vm.Script(SRC, { filename: 'overlay.js' }));
  assert.doesNotMatch(SRC, /^\s*(import|export)\s/m);
});

test('shortcuts never fire while typing in a field — the page\'s or one of ours inside the shadow root', () => {
  const kd = SRC.slice(SRC.indexOf("document.addEventListener('keydown'"));
  assert.match(kd, /composedPath\(\)\[0\]/, 'the real target, not the retargeted shadow host');
  assert.match(kd, /INPUT\|TEXTAREA\|SELECT/);
  assert.match(kd, /Escape' && panel\) \{ closePanel\(\)/, 'Escape closes a panel before it discards');
  assert.match(kd, /e\.key === 'c' \|\| e\.key === 'C'/, 'C toggles compare');
});

test('compare: apply() puts the page back before toggling variants; the slider restores every style it set', () => {
  const ap = fnBody('apply');
  assert.ok(ap.indexOf('clearCompare()') < ap.indexOf("style.display = on ? 'contents' : 'none'"), 'clear first, or a restore undoes the toggle');
  assert.match(ap, /setupCompare\(\)/);
  const clear = fnBody('clearCompare');
  assert.match(clear, /restoreStyle\(c\.w, c\.ws\); restoreStyle\(c\.o, c\.os\); restoreStyle\(c\.v, c\.vs\)/);
  const setup = fnBody('setupCompare');
  assert.match(setup, /idx === 0\) return/, 'nothing to compare on the original');
  assert.match(setup, /gridArea = '1 \/ 1'/);
  assert.match(setup, /pageBg\(/, 'the original covers the variant with the page background');
  assert.match(SRC, /localStorage\.getItem\('dh-compare'\) !== '0'/, 'on by default, remembered');
});

test('More sends the batch, keeps the session on a spent pool, and jumps to the first new variant', () => {
  const m = fnBody('doMore');
  assert.match(m, /api\('more', \{ id: sid, batch: batch/);
  assert.match(m, /POOL_EMPTY' \|\| r\.code === 'TOO_MANY_VARIANTS'\)\) \{ session = was/);
  assert.match(m, /startSession\(r, r\.startAt \|\| 1\)/);
  assert.match(SRC, /\[4, 6, 8, 12\]\.forEach/);
});

test('flags: the form prefills from what the page showed; errors are attributed to the variant on screen', () => {
  const ff = fnBody('flagForm');
  assert.match(ff, /autoCheck\(\)/);
  assert.match(ff, /api\('flag-add', \{ session: session\.id, idx: idx, reasons: rs/);
  const ac = fnBody('autoCheck');
  for (const k of ['missing', 'foreign', 'overflow', 'brokenImages', 'errors']) assert.match(ac, new RegExp(k));
  assert.match(fnBody('apply'), /errMark = pageErrors\.length/);
  assert.match(SRC, /api\('flag-report', \{\}\)/);
});

test('the overlay survives a framework re-rendering the whole body', () => {
  assert.match(SRC, /if \(!host\.isConnected\) \(document\.body \|\| document\.documentElement\)\.appendChild\(host\)/);
});
