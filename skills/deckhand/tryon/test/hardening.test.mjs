// Inputs from the helper API or the CLI are validated before they become CSS, class lists or file paths;
// Tune and Site work headless (same engine as the overlay) and stay byte-exact reversible.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { tempSite, locate, HERE, mktmp } from './helpers.mjs';
import { dialsOf, tuneOpen, tuneSet, tuneKeep, tuneReset } from '../lib/tune.mjs';
import { cleanTheme, themeApply, themeCss } from '../lib/sitetheme.mjs';
import { loadSession } from '../lib/engine.mjs';
import { loadDraft } from '../lib/draft.mjs';
import { saveDir } from '../lib/library.mjs';

const CLI = path.join(HERE, '..', 'cli.mjs');
const cli = (dir, ...args) => {
  const r = spawnSync(process.execPath, [CLI, ...args, '--project', dir], { encoding: 'utf8' });
  return { code: r.status, out: JSON.parse(r.stdout.trim().split('\n').pop()) };
};
const code = (fn) => { try { fn(); } catch (e) { return e.code; } return null; };

test('Site knobs: only known keys and values reach the stylesheet (no way out of the CSS comment)', () => {
  assert.equal(code(() => cleanTheme({ accent: '*/ body { display: none } /*' })), 'BAD_THEME');
  assert.equal(code(() => cleanTheme({ corners: 'huge' })), 'BAD_THEME');
  assert.equal(code(() => cleanTheme({ body: 'Comic_Sans' })), 'BAD_THEME');
  assert.equal(code(() => cleanTheme({ evil: 'x' })), 'BAD_THEME');
  assert.deepEqual(cleanTheme({ accent: '#0f766e', corners: 'soft', body: 'as is', density: '' }), { accent: '#0f766e', corners: 'soft' });
  assert.ok(!themeCss({ accent: 'teal', corners: 'soft' }).includes('*/ body'));
  const dir = tempSite();
  const css = fs.readFileSync(path.join(dir, 'app/globals.css'));
  assert.equal(code(() => themeApply(dir, { accent: 'teal', neutrals: '*/ html{} /*' })), 'BAD_THEME');
  assert.ok(fs.readFileSync(path.join(dir, 'app/globals.css')).equals(css), 'a refused apply writes nothing');
});

test('Tune dials: validated ranges and choices, ids never become paths, closed sessions stay closed', () => {
  assert.deepEqual(dialsOf({ density: '1' }, 'softer'), { corners: 'round', depth: 'subtle', density: 1 });
  assert.equal(code(() => dialsOf({ density: 9 })), 'BAD_DIAL');
  assert.equal(code(() => dialsOf({ corners: 'triangle' })), 'BAD_DIAL');
  assert.equal(code(() => dialsOf({ glow: 1 })), 'BAD_DIAL');
  assert.equal(code(() => dialsOf({}, 'louder')), 'BAD_DIAL');
  const dir = tempSite();
  assert.equal(code(() => tuneSet(dir, '../../etc/passwd', { dials: { density: 1 } })), 'BAD_ID');
  assert.equal(code(() => loadSession(dir, '../x')), 'BAD_ID');
  assert.equal(code(() => loadDraft(dir, 'a/b')), 'BAD_ID');
  fs.mkdirSync(path.join(dir, 'node_modules/x'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'node_modules/x/c.tsx'), 'export default () => <div className="p-4" />\n');
  assert.equal(code(() => tuneOpen(dir, { file: 'node_modules/x/c.tsx', line: 1, col: 23 })), 'GENERATED_FILE');
  const hero = fs.readFileSync(path.join(dir, 'components/hero.tsx'));
  const t = tuneOpen(dir, { file: 'components/hero.tsx', ...locate(hero.toString(), '<section') });
  tuneSet(dir, t.id, { preset: 'airy' });
  tuneReset(dir, t.id);
  assert.ok(fs.readFileSync(path.join(dir, 'components/hero.tsx')).equals(hero));
  assert.equal(code(() => tuneKeep(dir, t.id)), 'TUNE_CLOSED');
});

test('headless Tune and Site: `tryon tune` / `tryon theme` apply, then restore byte-exact', () => {
  const dir = tempSite();
  const heroPath = path.join(dir, 'components/hero.tsx');
  const hero = fs.readFileSync(heroPath);
  const at = locate(hero.toString(), '<section');
  const t = cli(dir, 'tune', '--file', 'components/hero.tsx', '--line', String(at.line), '--col', String(at.col), '--preset', 'airy');
  assert.equal(t.code, 0, JSON.stringify(t.out));
  assert.ok(t.out.changed > 0 && !fs.readFileSync(heroPath).equals(hero));
  assert.equal(cli(dir, 'tune', '--id', t.out.id, '--reset').code, 0);
  assert.ok(fs.readFileSync(heroPath).equals(hero));
  assert.equal(cli(dir, 'tune', '--file', 'components/hero.tsx', '--line', String(at.line), '--col', String(at.col), '--density', '7').out.code, 'BAD_DIAL');

  const cssPath = path.join(dir, 'app/globals.css');
  const css = fs.readFileSync(cssPath);
  const a = cli(dir, 'theme', '--accent', 'teal', '--corners', 'soft');
  assert.equal(a.code, 0, JSON.stringify(a.out));
  assert.match(fs.readFileSync(cssPath, 'utf8'), /dh:theme[\s\S]*--radius: 0\.375rem/);
  assert.deepEqual(cli(dir, 'theme').out.current, { accent: 'teal', corners: 'soft' });
  assert.equal(cli(dir, 'theme', '--undo').code, 0);
  assert.ok(fs.readFileSync(cssPath).equals(css));
  assert.equal(cli(dir, 'theme', '--corners', 'huge').out.code, 'BAD_THEME');
});

test('the personal library refuses every credential shape of the shared policy (data/secrets.json)', () => {
  const lib = mktmp('dh-lib-');
  process.env.DECKHAND_LIBRARY = lib;
  try {
    for (const secret of ['12|' + 'a'.repeat(44), 'sk-ant-' + 'b'.repeat(40), 'eyJ' + 'c'.repeat(24) + '.' + 'd'.repeat(24) + '.x']) {
      const src = fs.mkdtempSync(path.join(lib, 'src-'));
      fs.writeFileSync(path.join(src, 'x.tsx'), `export const k = "${secret}"\n`);
      assert.equal(code(() => saveDir({ dir: src, entry: 'x.tsx', name: 'leaky', slot: 'hero', lic: 'MIT', source: 'test', title: 'x' })), 'CREDENTIAL', secret.slice(0, 8));
    }
  } finally {
    fs.rmSync(lib, { recursive: true, force: true });
  }
});
