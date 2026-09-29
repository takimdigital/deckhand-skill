/**
 * setup.mjs — put the dev-only stamp into a project, and take it out again byte-exact.
 *
 * Next.js: next.config.* gets ONE wrapped export — `export default withDeckhandTryon(config)` —
 *   the plugin (copied into .deckhand/tryon/runtime/) adds the Turbopack rule (and the webpack
 *   rule under --webpack) only when NODE_ENV=development. The user's config object is untouched.
 * Vite: `dhTryon()` is prepended to `plugins: [...]` (apply: 'serve' — never in a build).
 * Everything is journaled in .deckhand/tryon/setup.json; `.deckhand/tryon/` is gitignored.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { detectProject } from './project.mjs';
import { stripTokenLayer } from './theme.mjs';

const require = createRequire(import.meta.url);
const { parse } = require('./ast.cjs');
const HERE = path.dirname(fileURLToPath(import.meta.url));
const TRYON = path.resolve(HERE, '..');
const MARK = 'deckhand-tryon';
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');

const NEXT_PLUGIN = `'use strict';
// ${MARK}: dev-only JSX source stamping for deckhand try-on. Removed by \`tryon clean\`.
const path = require('path');
const LOADER = path.join(__dirname, 'loader.cjs');

function nextVersion() {
  try { return require(require.resolve('next/package.json', { paths: [process.cwd()] })).version.split('.').map(Number); } catch { return [16, 0]; }
}

function apply(cfg) {
  if (process.env.NODE_ENV !== 'development' || process.env.DECKHAND_TRYON === '0') return cfg;
  const root = process.cwd();
  const use = [{ loader: LOADER, options: { root } }];
  // no \`as\`: the output keeps its type. (\`as: '*.tsx'\` renames the module and breaks every
  // 'use client' boundary — measured on Next 16.3.6: "Can't resolve './x.tsx.tsx'")
  const rules = { '*.tsx': { loaders: use }, '*.jsx': { loaders: use } };
  const [major, minor] = nextVersion();
  const out = { ...cfg };
  if (major > 15 || (major === 15 && minor >= 3)) {
    out.turbopack = { ...(cfg.turbopack || {}), rules: { ...((cfg.turbopack || {}).rules || {}), ...rules } };
  } else {
    const exp = cfg.experimental || {};
    out.experimental = { ...exp, turbo: { ...(exp.turbo || {}), rules: { ...((exp.turbo || {}).rules || {}), ...rules } } };
  }
  const usesWebpack = process.argv.includes('--webpack') || (major < 16 && !process.argv.some((a) => /^--turbo/.test(a)) && !process.env.TURBOPACK);
  if (usesWebpack) {
    const user = cfg.webpack;
    out.webpack = (wc, ctx) => {
      const r = user ? user(wc, ctx) : wc;
      if (ctx.dev) r.module.rules.unshift({ test: /\\.(jsx|tsx)$/, exclude: /node_modules/, enforce: 'pre', use });
      return r;
    };
  }
  return out;
}

function withDeckhandTryon(config) {
  if (typeof config === 'function') return async (...a) => apply(await config(...a));
  return apply(config);
}
module.exports = { withDeckhandTryon };
`;

function journalPath(root) { return path.join(root, '.deckhand', 'tryon', 'setup.json'); }
export function readJournal(root) {
  try { return JSON.parse(fs.readFileSync(journalPath(root), 'utf8')); } catch { return null; }
}

function copyRuntime(root) {
  const rt = path.join(root, '.deckhand', 'tryon', 'runtime');
  fs.mkdirSync(path.join(rt, 'lib'), { recursive: true });
  fs.mkdirSync(path.join(rt, 'vendor'), { recursive: true });
  for (const f of ['loader.cjs', 'vite.mjs', 'lib/stamp.cjs', 'lib/ast.cjs', 'vendor/babel-parser.cjs', 'vendor/LICENSE-babel-parser']) {
    fs.copyFileSync(path.join(TRYON, f), path.join(rt, f));
  }
  fs.writeFileSync(path.join(rt, 'next-plugin.cjs'), NEXT_PLUGIN);
  return rt;
}

function findConfig(root, names) { return names.find((n) => fs.existsSync(path.join(root, n))) || null; }

/** Wrap the default export of next.config.* (ESM/TS) or module.exports (CJS). */
export function patchNextConfig(file, code) {
  if (code.includes(MARK)) return { code, changed: false };
  const ast = parse(file, code);
  const isCjs = /\.cjs$/.test(file) || (!ast.program.body.some((s) => /^(Import|Export)/.test(s.type)) && /module\.exports\s*=/.test(code));
  let target = null;
  for (const st of ast.program.body) {
    if (st.type === 'ExportDefaultDeclaration') target = st.declaration;
    if (st.type === 'ExpressionStatement' && st.expression.type === 'AssignmentExpression'
      && code.slice(st.expression.left.start, st.expression.left.end).replace(/\s/g, '') === 'module.exports') target = st.expression.right;
  }
  if (!target) throw Object.assign(new Error('NO_CONFIG_EXPORT: cannot find the exported Next config in ' + file), { code: 'NO_CONFIG_EXPORT' });
  let out = code.slice(0, target.start) + 'withDeckhandTryon(' + code.slice(target.start, target.end) + ')' + code.slice(target.end);
  const line = isCjs
    ? `const { withDeckhandTryon } = require("./.deckhand/tryon/runtime/next-plugin.cjs"); // ${MARK}\n`
    : `import { withDeckhandTryon } from "./.deckhand/tryon/runtime/next-plugin.cjs"; // ${MARK}\n`;
  let at = 0;
  const imports = ast.program.body.filter((s) => s.type === 'ImportDeclaration');
  if (imports.length) at = out.indexOf('\n', imports[imports.length - 1].end) + 1;
  out = out.slice(0, at) + line + out.slice(at);
  parse(file, out);
  return { code: out, changed: true };
}

export function patchViteConfig(file, code) {
  if (code.includes(MARK)) return { code, changed: false };
  const ast = parse(file, code);
  let arr = null;
  const { walk } = require('./ast.cjs');
  walk(ast, (n) => {
    if (arr) return false;
    if (n.type === 'ObjectProperty' && (n.key.name === 'plugins' || n.key.value === 'plugins') && n.value.type === 'ArrayExpression') { arr = n.value; return false; }
    return true;
  });
  if (!arr) throw Object.assign(new Error('NO_PLUGINS_ARRAY: add `plugins: []` to ' + file), { code: 'NO_PLUGINS_ARRAY' });
  let out = code.slice(0, arr.start + 1) + 'dhTryon(), ' + code.slice(arr.start + 1);
  const line = `import dhTryon from "./.deckhand/tryon/runtime/vite.mjs"; // ${MARK}\n`;
  const imports = ast.program.body.filter((s) => s.type === 'ImportDeclaration');
  const at = imports.length ? out.indexOf('\n', imports[imports.length - 1].end) + 1 : 0;
  out = out.slice(0, at) + line + out.slice(at);
  parse(file, out);
  return { code: out, changed: true };
}

export function setup(rootIn) {
  const prof = detectProject(rootIn);
  const root = prof.root;
  const journal = readJournal(root) || { files: [], createdAt: new Date().toISOString() };
  copyRuntime(root);
  let cfgFile = null, res = null;
  if (prof.framework === 'next') {
    cfgFile = findConfig(root, ['next.config.ts', 'next.config.mjs', 'next.config.js', 'next.config.cjs', 'next.config.mts']);
    if (!cfgFile) { cfgFile = 'next.config.mjs'; fs.writeFileSync(path.join(root, cfgFile), 'export default {};\n'); journal.created = (journal.created || []).concat(cfgFile); }
    const code = fs.readFileSync(path.join(root, cfgFile), 'utf8');
    res = patchNextConfig(cfgFile, code);
  } else if (prof.framework === 'vite') {
    cfgFile = findConfig(root, ['vite.config.ts', 'vite.config.mts', 'vite.config.js', 'vite.config.mjs']);
    if (!cfgFile) throw Object.assign(new Error('NO_VITE_CONFIG'), { code: 'NO_VITE_CONFIG' });
    res = patchViteConfig(cfgFile, fs.readFileSync(path.join(root, cfgFile), 'utf8'));
  } else {
    return { ok: false, code: 'UNSUPPORTED_FRAMEWORK', framework: prof.framework, hint: 'degraded mode: `tryon try --file <f> --line <n> --col <c> --slot <s>` still works; the overlay needs Next.js or Vite' };
  }
  if (res.changed) {
    const abs = path.join(root, cfgFile);
    const bdir = path.join(root, '.deckhand', 'tryon', 'backups', 'setup');
    fs.mkdirSync(bdir, { recursive: true });
    fs.writeFileSync(path.join(bdir, path.basename(cfgFile) + '.orig'), fs.readFileSync(abs));
    fs.writeFileSync(abs, res.code);
    journal.files = journal.files.filter((f) => f.path !== cfgFile).concat({ path: cfgFile, backup: `.deckhand/tryon/backups/setup/${path.basename(cfgFile)}.orig`, shaAfter: sha(Buffer.from(res.code)) });
  }
  // gitignore the state dir (tokens, journals, backups never belong in git)
  const gi = path.join(root, '.gitignore');
  const giText = fs.existsSync(gi) ? fs.readFileSync(gi, 'utf8') : '';
  if (!/^\/?\.deckhand\/tryon\/?$/m.test(giText)) {
    if (!fs.existsSync(gi)) journal.gitignoreCreated = true;
    fs.writeFileSync(gi, giText.replace(/\s*$/, '\n') + `\n# ${MARK} state (journal, backups, dev runtime)\n.deckhand/tryon/\n`);
    journal.gitignore = true;
  }
  fs.mkdirSync(path.dirname(journalPath(root)), { recursive: true });
  fs.writeFileSync(journalPath(root), JSON.stringify(journal, null, 2));
  return { ok: true, framework: prof.framework, config: cfgFile, patched: res.changed, restartDevServer: res.changed };
}

/** Undo setup. Kept variants keep the token layer they render with. */
export function unsetup(rootIn, { keepTokens = null } = {}) {
  const prof = detectProject(rootIn);
  const root = prof.root;
  const j = readJournal(root);
  const out = { restored: [], tokens: 'untouched' };
  if (j) {
    for (const f of j.files) {
      const abs = path.join(root, f.path);
      if (!fs.existsSync(abs)) continue;
      const cur = fs.readFileSync(abs);
      if (sha(cur) === f.shaAfter) { fs.writeFileSync(abs, fs.readFileSync(path.join(root, f.backup))); out.restored.push(f.path + ' (byte-exact)'); continue; }
      let code = cur.toString('utf8').split('\n').filter((l) => !l.includes(`// ${MARK}`)).join('\n');
      code = code.replace(/withDeckhandTryon\(([\s\S]*?)\)(\s*;?\s*)$/m, '$1$2').replace(/withDeckhandTryon\(/g, '(').replace(/dhTryon\(\),\s*/g, '');
      fs.writeFileSync(abs, code);
      out.restored.push(f.path + ' (surgical)');
    }
    for (const c of j.created || []) { try { fs.unlinkSync(path.join(root, c)); } catch { /* gone */ } }
    if (j.gitignore) {
      const gi = path.join(root, '.gitignore');
      // the lines setup added, CRLF too (an editor on Windows may have rewritten the file); a file setup created goes
      if (fs.existsSync(gi)) {
        const text = fs.readFileSync(gi, 'utf8').replace(new RegExp(`(\\r?\\n)*# ${MARK} state \\(journal, backups, dev runtime\\)\\r?\\n\\.deckhand/tryon/(\\r?\\n)?`), (m, a) => (a || ''));
        if (j.gitignoreCreated && !text.trim()) fs.unlinkSync(gi);
        else fs.writeFileSync(gi, text);
      }
    }
  }
  if (keepTokens === false && prof.globalsCss) {
    const p = path.join(root, prof.globalsCss);
    fs.writeFileSync(p, stripTokenLayer(fs.readFileSync(p, 'utf8')));
    out.tokens = 'removed';
  } else if (keepTokens) out.tokens = 'kept (kept variants use them)';
  fs.rmSync(path.join(root, '.deckhand', 'tryon', 'runtime'), { recursive: true, force: true });
  try { fs.unlinkSync(journalPath(root)); } catch { /* none */ }
  return out;
}
