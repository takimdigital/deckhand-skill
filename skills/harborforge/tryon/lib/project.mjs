/**
 * project.mjs — a measured profile of the target project (never assumed):
 * framework, aliases, where ui/lib live, package manager, installed deps, Tailwind major,
 * the global stylesheet, whether shadcn-style semantic tokens exist, and the primitive base.
 */
import fs from 'node:fs';
import path from 'node:path';

const exists = (p) => { try { fs.accessSync(p); return true; } catch { return false; } };
const readJson = (p) => { try { return JSON.parse(stripJsonComments(fs.readFileSync(p, 'utf8'))); } catch { return null; } };

/** tsconfig/jsconfig allow comments + trailing commas. */
export function stripJsonComments(s) {
  let out = '', inStr = false, q = '';
  for (let i = 0; i < s.length; i++) {
    const c = s[i], n = s[i + 1];
    if (inStr) {
      out += c;
      if (c === '\\') { out += n; i++; continue; }
      if (c === q) inStr = false;
      continue;
    }
    if (c === '"' || c === "'") { inStr = true; q = c; out += c; continue; }
    if (c === '/' && n === '/') { while (i < s.length && s[i] !== '\n') i++; out += '\n'; continue; }
    if (c === '/' && n === '*') { i += 2; while (i < s.length && !(s[i] === '*' && s[i + 1] === '/')) i++; i++; continue; }
    out += c;
  }
  return out.replace(/,(\s*[}\]])/g, '$1');
}

const PM = [['pnpm-lock.yaml', 'pnpm'], ['bun.lockb', 'bun'], ['bun.lock', 'bun'], ['yarn.lock', 'yarn'], ['package-lock.json', 'npm']];

export function detectProject(rootIn) {
  const root = path.resolve(rootIn);
  const pkg = readJson(path.join(root, 'package.json')) || {};
  const deps = { ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) };
  const has = (d) => Object.prototype.hasOwnProperty.call(deps, d);

  const framework = has('next') ? 'next' : (has('vite') ? 'vite' : (has('react-scripts') ? 'cra' : 'unknown'));
  const nextMajor = has('next') ? Number(String(readJson(path.join(root, 'node_modules/next/package.json'))?.version || deps.next).replace(/^[^\d]*/, '').split('.')[0]) || null : null;

  const tsconfig = readJson(path.join(root, 'tsconfig.json')) || readJson(path.join(root, 'jsconfig.json')) || {};
  const co = tsconfig.compilerOptions || {};
  const paths = co.paths || {};
  const baseUrl = co.baseUrl || '.';
  const components = readJson(path.join(root, 'components.json'));

  const srcDir = exists(path.join(root, 'src/app')) || exists(path.join(root, 'src/components')) || exists(path.join(root, 'src/main.tsx'));
  const appDir = ['app', 'src/app'].find((d) => exists(path.join(root, d))) || null;

  // alias prefix that maps to the project root or src ("@/" in 95% of projects)
  let alias = null, aliasTarget = null;
  for (const [k, v] of Object.entries(paths)) {
    if (!k.endsWith('/*')) continue;
    const t = String((v || [])[0] || '').replace(/\*$/, '').replace(/^\.\//, '').replace(/\/$/, '');
    alias = k.slice(0, -1);            // "@/"
    aliasTarget = path.posix.join(baseUrl === '.' ? '' : baseUrl, t) || '.';
    break;
  }
  const codeRoot = aliasTarget && aliasTarget !== '.' ? aliasTarget : (srcDir ? 'src' : '.');

  const fromAlias = (a) => (alias && a && a.startsWith(alias) ? path.posix.join(codeRoot === '.' ? '' : codeRoot, a.slice(alias.length)) : null);
  const aliases = components?.aliases || {};
  const uiDir = fromAlias(aliases.ui) || path.posix.join(codeRoot === '.' ? '' : codeRoot, 'components/ui');
  const componentsDir = fromAlias(aliases.components) || path.posix.join(codeRoot === '.' ? '' : codeRoot, 'components');
  const utilsFile = (fromAlias(aliases.utils) || path.posix.join(codeRoot === '.' ? '' : codeRoot, 'lib/utils'));
  const hooksDir = fromAlias(aliases.hooks) || path.posix.join(codeRoot === '.' ? '' : codeRoot, 'hooks');

  const pm = (PM.find(([f]) => exists(path.join(root, f))) || [null, 'npm'])[1];

  const twVersion = String(deps.tailwindcss || '').replace(/^[^\d]*/, '');
  const tailwind = twVersion ? Number(twVersion.split('.')[0]) : null;

  const cssCandidates = [components?.tailwind?.css, 'app/globals.css', 'src/app/globals.css', 'styles/globals.css',
    'src/styles/globals.css', 'src/index.css', 'src/globals.css', 'app/global.css'].filter(Boolean);
  const globalsCss = cssCandidates.find((c) => exists(path.join(root, c))) || null;
  const cssText = globalsCss ? fs.readFileSync(path.join(root, globalsCss), 'utf8') : '';
  const tokens = {
    primary: /--primary\s*:/.test(cssText) || /--color-primary\s*:/.test(cssText),
    muted: /--muted-foreground\s*:/.test(cssText) || /--color-muted-foreground\s*:/.test(cssText),
    border: /--border\s*:/.test(cssText) || /--color-border\s*:/.test(cssText),
    radius: /--radius\s*:/.test(cssText),
  };

  const base = has('@base-ui-components/react') || has('@base-ui/react') ? 'base-ui'
    : (Object.keys(deps).some((d) => d.startsWith('@radix-ui/')) || has('radix-ui') ? 'radix' : 'none');

  const ui = {};
  const uiAbs = path.join(root, uiDir);
  if (exists(uiAbs)) {
    for (const f of fs.readdirSync(uiAbs)) {
      const m = /^(.+)\.(tsx|jsx|ts|js)$/.exec(f);
      if (m) ui[m[1]] = path.posix.join(uiDir, f);
    }
  }
  const utilsExists = ['.ts', '.tsx', '.js'].some((e) => exists(path.join(root, utilsFile + e)));
  const lang = exists(path.join(root, 'tsconfig.json')) ? 'ts' : 'js';

  return {
    root, framework, nextMajor, pm, lang, alias: alias || '@/', codeRoot, appDir, srcDir,
    uiDir, componentsDir, utilsFile, utilsExists, hooksDir, ui, deps, tailwind, globalsCss, tokens, base,
    hasShadcnConfig: !!components, rsc: components?.rsc ?? (framework === 'next' && !!appDir),
  };
}

/** Import specifier for a project-relative file path (posix, without extension). */
export function specFor(prof, relFile) {
  const noExt = relFile.replace(/\.(tsx|ts|jsx|js)$/, '');
  const cr = prof.codeRoot === '.' ? '' : prof.codeRoot + '/';
  if (prof.alias && (cr === '' || noExt.startsWith(cr))) return prof.alias + noExt.slice(cr.length);
  return null;
}

/** Is an npm package resolvable from the project (declared AND present in node_modules)? */
export function depInstalled(prof, name) {
  return Object.prototype.hasOwnProperty.call(prof.deps, name) && exists(path.join(prof.root, 'node_modules', name, 'package.json'));
}
