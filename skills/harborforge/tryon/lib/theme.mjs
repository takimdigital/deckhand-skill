/**
 * theme.mjs — make a registry component wear the SITE's colours, deterministically.
 *
 * 1. normalizeClasses(): hard-coded Tailwind palette classes become semantic tokens
 *    (bg-zinc-100 -> bg-muted, bg-indigo-600 -> bg-primary, text-gray-500 -> text-muted-foreground);
 *    `dark:` palette twins are dropped because tokens already flip with the theme.
 *    Only class-list strings are touched (className, cn/clsx/cva/tv args) — AST-located.
 * 2. tokenLayer(): for a project WITHOUT semantic tokens, the missing ones are derived from the
 *    site's own --background/--foreground (color-mix), so blocks inherit its palette and dark mode.
 *    An accent probed from the live page (overlay) becomes --primary.
 */
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { parse, walk } = require('./ast.cjs');

const NEUTRAL = '(?:zinc|gray|grey|slate|neutral|stone)';
const ACCENT = '(?:blue|indigo|violet|purple|sky|cyan|teal|pink|fuchsia|rose|orange)';
const SHADE = '(?:50|100|200|300|400|500|600|700|800|900|950)';
const CLASS_FNS = new Set(['cn', 'clsx', 'cva', 'tv', 'twMerge', 'classNames', 'cx', 'twJoin']);

function mapOne(cls, siblings) {
  const m = /^((?:[a-z0-9-]+:)*)(.+)$/.exec(cls);
  const variants = m[1], core = m[2];
  const isDark = /(^|:)dark:/.test(variants);
  let r;
  const op = (s) => { const i = s.lastIndexOf('/'); return i > 0 && /^\d+$/.test(s.slice(i + 1)) ? s.slice(i) : ''; };
  const bare = core.replace(/\/\d+$/, '');
  const o = op(core);
  const n = (re) => new RegExp('^' + re + '$').test(bare);

  if (n(`bg-${NEUTRAL}-(?:50|100|200)`)) r = 'bg-muted';
  else if (n(`bg-${NEUTRAL}-(?:300|400)`)) r = 'bg-border';
  else if (n(`bg-${NEUTRAL}-(?:800|900|950)`) || bare === 'bg-black') r = 'bg-foreground';
  else if (bare === 'bg-white') r = 'bg-background';
  else if (n(`text-${NEUTRAL}-(?:300|400|500|600)`)) r = 'text-muted-foreground';
  else if (n(`text-${NEUTRAL}-(?:700|800|900|950)`) || bare === 'text-black') r = 'text-foreground';
  else if (n(`(border|divide|ring|outline)-${NEUTRAL}-${SHADE}`)) r = bare.split('-')[0] + '-border';
  else if (n(`bg-${ACCENT}-(?:400|500|600|700|800)`)) r = 'bg-primary';
  else if (n(`bg-${ACCENT}-(?:50|100|200)`)) r = 'bg-primary/10';
  else if (n(`text-${ACCENT}-(?:400|500|600|700|800|900)`)) r = 'text-primary';
  else if (n(`(border|ring|outline|fill|stroke|decoration|caret|accent)-${ACCENT}-${SHADE}`)) r = bare.split('-')[0] + '-primary';
  else if (n(`(from|via|to|shadow)-${ACCENT}-${SHADE}`)) r = bare.split('-')[0] + '-primary';
  else if (bare === 'text-white') {
    if (siblings.some((s) => /(^|:)bg-(primary|(?:blue|indigo|violet|purple|sky|cyan|teal|pink|fuchsia|rose|orange)-\d)/.test(s))) r = 'text-primary-foreground';
    else if (siblings.some((s) => /(^|:)bg-(foreground|black|(?:zinc|gray|slate|neutral|stone)-(?:800|900|950))/.test(s))) r = 'text-background';
  }
  if (!r) return cls;
  if (isDark) return null;                         // the token already flips in dark mode
  if (/^(hover|focus|active)/.test(variants) && r === 'bg-primary') return variants + 'bg-primary/90';
  return variants + r + (r.includes('/') ? '' : o);
}

export function normalizeClassList(str) {
  if (!/[a-z]/.test(str)) return str;
  const lead = str.match(/^\s*/)[0], trail = str.match(/\s*$/)[0];
  const parts = str.trim().split(/\s+/);
  const out = [];
  for (const p of parts) {
    const v = mapOne(p, parts);
    if (v !== null && !out.includes(v)) out.push(v);
  }
  const joined = out.join(' ');
  return joined === str.trim() ? str : lead + joined + trail;
}

/** Rewrite class-list string literals in a source file. Returns { code, changed }. */
export function normalizeClasses(file, code) {
  let ast;
  try { ast = parse(file, code); } catch { return { code, changed: 0 }; }
  const edits = [];
  const visitStrings = (node) => walk(node, (n) => {
    if (n.type === 'StringLiteral') {
      const next = normalizeClassList(n.value);
      if (next !== n.value) {
        const q = code[n.start];
        edits.push({ start: n.start, end: n.end, text: q + next.replace(new RegExp(q, 'g'), '\\' + q) + q });
      }
      return false;
    }
    if (n.type === 'TemplateElement') {
      const raw = n.value.raw;
      const next = normalizeClassList(raw);
      if (next !== raw) edits.push({ start: n.start, end: n.end, text: next });
      return false;
    }
    return true;
  });
  walk(ast, (n) => {
    if (n.type === 'JSXAttribute' && n.name && /^(className|class)$/.test(n.name.name) && n.value) { visitStrings(n.value); return false; }
    if (n.type === 'CallExpression' && n.callee.type === 'Identifier' && CLASS_FNS.has(n.callee.name)) { n.arguments.forEach(visitStrings); return false; }
    return true;
  });
  if (!edits.length) return { code, changed: 0 };
  edits.sort((a, b) => b.start - a.start);
  let out = code;
  for (const e of edits) out = out.slice(0, e.start) + e.text + out.slice(e.end);
  return { code: out, changed: edits.length };
}

const TOKENS = {
  background: null, foreground: null,
  card: 'var(--background)', 'card-foreground': 'var(--foreground)',
  popover: 'var(--background)', 'popover-foreground': 'var(--foreground)',
  primary: 'var(--foreground)', 'primary-foreground': 'var(--background)',
  secondary: 'color-mix(in oklab, var(--foreground) 6%, var(--background))', 'secondary-foreground': 'var(--foreground)',
  muted: 'color-mix(in oklab, var(--foreground) 5%, var(--background))',
  'muted-foreground': 'color-mix(in oklab, var(--foreground) 62%, var(--background))',
  accent: 'color-mix(in oklab, var(--foreground) 6%, var(--background))', 'accent-foreground': 'var(--foreground)',
  destructive: 'oklch(0.577 0.245 27.325)',
  border: 'color-mix(in oklab, var(--foreground) 12%, var(--background))',
  input: 'color-mix(in oklab, var(--foreground) 16%, var(--background))',
  ring: 'color-mix(in oklab, var(--foreground) 40%, var(--background))',
};

export const TOKENS_BEGIN = '/* deckhand:tokens — semantic tokens for registry components, derived from this site (added by try-on setup; `tryon clean` removes it) */';
export const TOKENS_END = '/* /deckhand:tokens */';

/**
 * The token layer for a Tailwind v4 stylesheet. Only tokens the file lacks are declared.
 * probe = { background, foreground, primary, primaryForeground, radius } from the live page (optional).
 */
export function tokenLayer(cssText, probe = {}) {
  const has = (t) => new RegExp('--' + t + '\\s*:').test(cssText);
  const hasTheme = (t) => new RegExp('--color-' + t + '\\s*:').test(cssText);
  const root = [];
  const theme = [];
  for (const [t, def] of Object.entries(TOKENS)) {
    let v = def;
    if (t === 'background') v = probe.background || '#ffffff';
    if (t === 'foreground') v = probe.foreground || '#0a0a0a';
    if (t === 'primary' && probe.primary) v = probe.primary;
    if (t === 'primary-foreground' && probe.primaryForeground) v = probe.primaryForeground;
    if (!has(t)) root.push(`  --${t}: ${v};`);
    if (!hasTheme(t)) theme.push(`  --color-${t}: var(--${t});`);
  }
  if (!has('radius')) root.push(`  --radius: ${probe.radius || '0.625rem'};`);
  if (!/--radius-lg\s*:/.test(cssText)) {
    theme.push('  --radius-sm: calc(var(--radius) - 4px);', '  --radius-md: calc(var(--radius) - 2px);',
      '  --radius-lg: var(--radius);', '  --radius-xl: calc(var(--radius) + 4px);');
  }
  if (!root.length && !theme.length) return '';
  // starts with '\n' (a blank separator line) and ends with '\n': stripTokenLayer is its exact inverse
  return '\n' + [TOKENS_BEGIN,
    root.length ? ':root {\n' + root.join('\n') + '\n}' : '',
    theme.length ? '@theme inline {\n' + theme.join('\n') + '\n}' : '',
    TOKENS_END].filter((l) => l !== '').join('\n') + '\n';
}

export function stripTokenLayer(cssText) {
  const a = cssText.indexOf(TOKENS_BEGIN);
  if (a === -1) return cssText;
  const b = cssText.indexOf(TOKENS_END, a);
  if (b === -1) return cssText;
  let start = a;
  if (cssText[start - 1] === '\n') start -= 1;
  return cssText.slice(0, start) + cssText.slice(b + TOKENS_END.length + (cssText[b + TOKENS_END.length] === '\n' ? 1 : 0));
}

/** A registry item's cssVars/css as a Tailwind v4 block (keyframes + theme animation vars). */
export function itemCss(item, tag) {
  const lines = [];
  const theme = item.cssVars?.theme || {};
  if (Object.keys(theme).length) {
    lines.push('@theme inline {');
    for (const [k, v] of Object.entries(theme)) lines.push(`  --${k}: ${v};`);
    lines.push('}');
  }
  const emit = (obj, indent) => {
    for (const [sel, body] of Object.entries(obj)) {
      if (body && typeof body === 'object') {
        lines.push(indent + sel + ' {');
        emit(body, indent + '  ');
        lines.push(indent + '}');
      } else {
        lines.push(indent + sel + ': ' + body + ';');
      }
    }
  };
  if (item.css) emit(item.css, '');
  if (!lines.length) return '';
  return `/* dh:css ${tag} */\n${lines.join('\n')}\n/* /dh:css ${tag} */\n`;
}
