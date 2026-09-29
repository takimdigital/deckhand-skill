/**
 * sitetheme.mjs — the whole site's look in six knobs, previewed instantly, applied exactly.
 *
 *   accent       a curated palette (or any hex) → --primary / --primary-foreground / --ring, light + dark
 *   neutrals     as is · neutral · warm · cool → background, card, muted, border… tinted consistently
 *   corners      sharp · soft · as is · round · pill → --radius
 *   density      compact · snug · as is · airy · spacious → --spacing (Tailwind 4 spacing scale)
 *   headlines    smaller · as is · larger · display → --text-2xl … --text-9xl
 *   fonts        body + heading from a curated Google Fonts list (Next.js next/font: an exact AST rewrite)
 * Colours, radius, spacing and type are CSS variables: the overlay previews them on :root with the exact
 * values that get written, in one marked block at the end of globals.css (`dh:theme`). Undo restores the
 * previous files byte-exact.
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { detectProject } from './project.mjs';

const require = createRequire(import.meta.url);
const { parse, walk } = require('./ast.cjs');

export const ACCENTS = {
  ink: 'oklch(0.21 0.006 285)', terracotta: 'oklch(0.62 0.15 40)', amber: 'oklch(0.70 0.16 65)', olive: 'oklch(0.58 0.11 125)',
  emerald: 'oklch(0.60 0.13 160)', teal: 'oklch(0.60 0.10 195)', ocean: 'oklch(0.55 0.15 245)', indigo: 'oklch(0.52 0.18 275)',
  plum: 'oklch(0.50 0.16 320)', rose: 'oklch(0.60 0.18 15)',
};
export const FONTS = [
  { id: 'Inter', google: 'Inter', kind: 'sans' }, { id: 'Geist', google: 'Geist', kind: 'sans' },
  { id: 'Manrope', google: 'Manrope', kind: 'sans' }, { id: 'DM_Sans', google: 'DM Sans', kind: 'sans' },
  { id: 'Plus_Jakarta_Sans', google: 'Plus Jakarta Sans', kind: 'sans' }, { id: 'Outfit', google: 'Outfit', kind: 'sans' },
  { id: 'Figtree', google: 'Figtree', kind: 'sans' }, { id: 'Space_Grotesk', google: 'Space Grotesk', kind: 'sans' },
  { id: 'Fraunces', google: 'Fraunces', kind: 'serif' }, { id: 'Playfair_Display', google: 'Playfair Display', kind: 'serif' },
  { id: 'Newsreader', google: 'Newsreader', kind: 'serif' }, { id: 'Instrument_Serif', google: 'Instrument Serif', kind: 'serif', weight: '400' },
  { id: 'DM_Serif_Display', google: 'DM Serif Display', kind: 'serif', weight: '400' },
];
export const KNOBS = {
  accent: ['as is', ...Object.keys(ACCENTS)],
  neutrals: ['as is', 'neutral', 'warm', 'cool'],
  corners: { 'sharp': '0rem', 'soft': '0.375rem', 'as is': null, 'round': '0.875rem', 'pill': '1.25rem' },
  density: { 'compact': '0.22rem', 'snug': '0.235rem', 'as is': null, 'airy': '0.27rem', 'spacious': '0.29rem' },
  headlines: { 'smaller': 0.88, 'as is': 1, 'larger': 1.12, 'display': 1.25 },
};
const HEX = /^#[0-9a-f]{3}(?:[0-9a-f]{3})?$/i;
const OKLCH = /^oklch\(\s*[0-9.]+%?\s+[0-9.]+\s+[0-9.]+\s*\)$/i;

/** Validate Site knobs: known keys, known values (or a #hex / oklch() accent). Throws BAD_THEME with what is allowed. */
export function cleanTheme(v = {}) {
  const bad = (m) => Object.assign(new Error(m), { code: 'BAD_THEME' });
  const out = {};
  for (const [k, val] of Object.entries(v || {})) {
    if (val == null || val === '') continue;
    const s = String(val);
    if (k === 'accent') {
      if (!(s === 'as is' || ACCENTS[s] || HEX.test(s) || OKLCH.test(s))) throw bad(`accent: ${Object.keys(ACCENTS).join(', ')}, a #hex or oklch(L C H)`);
    } else if (k === 'neutrals') {
      if (!KNOBS.neutrals.includes(s)) throw bad(`neutrals: ${KNOBS.neutrals.join(', ')}`);
    } else if (k === 'corners' || k === 'density' || k === 'headlines') {
      if (!Object.prototype.hasOwnProperty.call(KNOBS[k], s)) throw bad(`${k}: ${Object.keys(KNOBS[k]).join(', ')}`);
    } else if (k === 'body' || k === 'heading') {
      if (s !== 'as is' && !FONTS.some((f) => f.id === s)) throw bad(`${k}: ${FONTS.map((f) => f.id).join(', ')}`);
      if (s === 'as is') continue;
    } else {
      throw bad(`unknown knob "${k}" (accent, neutrals, corners, density, headlines, body, heading)`);
    }
    out[k] = s;
  }
  return out;
}

const TEXT = { '2xl': 1.5, '3xl': 1.875, '4xl': 2.25, '5xl': 3, '6xl': 3.75, '7xl': 4.5, '8xl': 6, '9xl': 8 };
const BEGIN = '/* dh:theme — written by deckhand try-on (Site); edit freely or `tryon theme --undo` */';
const END = '/* /dh:theme */';

function oklchOf(c) {
  const m = /oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/.exec(c || '');
  if (m) return { L: +m[1], C: +m[2], H: +m[3] };
  const h = /^#?([0-9a-f]{6})$/i.exec(c || '');
  if (!h) return null;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h[1].slice(i, i + 2), 16) / 255).map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b), m2 = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b), s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l + 0.793617785 * m2 - 0.0040720468 * s, a = 1.9779984951 * l - 2.428592205 * m2 + 0.4505937099 * s, bb = 0.0259040371 * l + 0.7827717662 * m2 - 0.808675766 * s;
  return { L, C: Math.hypot(a, bb), H: ((Math.atan2(bb, a) * 180) / Math.PI + 360) % 360 };
}
const fmt = ({ L, C, H }) => `oklch(${L.toFixed(3)} ${C.toFixed(3)} ${H.toFixed(1)})`;

function neutrals(kind) {
  if (kind === 'as is') return null;
  const H = kind === 'warm' ? 70 : kind === 'cool' ? 250 : 0, c = kind === 'neutral' ? 0 : 1;
  const n = (L, C) => fmt({ L, C: C * c, H });
  return {
    light: { background: n(0.99, 0.004), foreground: n(0.17, 0.008), card: n(0.995, 0.003), 'card-foreground': n(0.17, 0.008), popover: n(0.995, 0.003),
      'popover-foreground': n(0.17, 0.008), secondary: n(0.965, 0.006), 'secondary-foreground': n(0.22, 0.01), muted: n(0.965, 0.006),
      'muted-foreground': n(0.52, 0.012), accent: n(0.955, 0.008), 'accent-foreground': n(0.22, 0.01), border: n(0.91, 0.006), input: n(0.91, 0.006) },
    dark: { background: n(0.16, 0.008), foreground: n(0.97, 0.004), card: n(0.2, 0.01), 'card-foreground': n(0.97, 0.004), popover: n(0.2, 0.01),
      'popover-foreground': n(0.97, 0.004), secondary: n(0.27, 0.012), 'secondary-foreground': n(0.97, 0.004), muted: n(0.27, 0.012),
      'muted-foreground': n(0.71, 0.012), accent: n(0.27, 0.012), 'accent-foreground': n(0.97, 0.004), border: 'oklch(1 0 0 / 10%)', input: 'oklch(1 0 0 / 15%)' },
  };
}

/** The exact variable values for a choice of knobs — the overlay previews these, apply writes these. */
export function themeVars(vIn = {}) {
  const v = cleanTheme(vIn);
  const light = {}, dark = {};
  const acc = v.accent && v.accent !== 'as is' ? (ACCENTS[v.accent] || v.accent) : null;
  const o = acc && oklchOf(acc);
  if (o) {
    light.primary = fmt(o);
    light['primary-foreground'] = o.L < 0.68 ? 'oklch(0.985 0 0)' : 'oklch(0.2 0.01 ' + o.H.toFixed(1) + ')';
    light.ring = fmt({ ...o, C: o.C * 0.6 });
    const d = { ...o, L: Math.min(0.82, o.L + 0.14) };
    dark.primary = fmt(d);
    dark['primary-foreground'] = d.L < 0.68 ? 'oklch(0.985 0 0)' : 'oklch(0.2 0.01 ' + o.H.toFixed(1) + ')';
    dark.ring = fmt({ ...d, C: d.C * 0.6 });
  }
  const n = neutrals(v.neutrals || 'as is');
  if (n) { Object.assign(light, n.light); Object.assign(dark, n.dark); }
  if (v.corners && KNOBS.corners[v.corners]) light.radius = KNOBS.corners[v.corners];
  if (v.density && KNOBS.density[v.density]) light.spacing = KNOBS.density[v.density];
  const f = KNOBS.headlines[v.headlines || 'as is'];
  if (f && f !== 1) for (const [k, rem] of Object.entries(TEXT)) light['text-' + k] = `${+(rem * f).toFixed(3)}rem`;
  return { light, dark };
}

export function themeCss(vIn, fonts = {}) {
  const v = cleanTheme(vIn);
  const { light, dark } = themeVars(v);
  const rules = [];
  // the body font must win over a stylesheet that hard-codes one (create-next-app: `body { font-family: Arial }`)
  if (fonts.bodyVar) rules.push(`body {\n  font-family: var(${fonts.bodyVar}), ui-sans-serif, system-ui, sans-serif;\n}\n`);
  // headings: in the base layer, so an explicit font utility on a heading still wins
  if (fonts.heading) rules.push('@layer base {\n  h1, h2, h3 { font-family: var(--font-heading), ui-serif, Georgia, serif; }\n}\n');
  if (!Object.keys(light).length && !Object.keys(dark).length && !rules.length) return '';
  const block = (sel, o) => (Object.keys(o).length ? `${sel} {\n${Object.entries(o).map(([k, val]) => `  --${k}: ${val};`).join('\n')}\n}\n` : '');
  return `${BEGIN}\n/* ${JSON.stringify(v)} */\n${block(':root', light)}${block('.dark', dark)}${rules.join('')}${END}\n`;
}

function stripBlock(css) {
  const a = css.indexOf(BEGIN);
  if (a < 0) return css;
  const b = css.indexOf(END, a);
  return css.slice(0, a).replace(/\n+$/, '\n') + css.slice(b + END.length).replace(/^\n+/, '');
}

/* ------------------------------------------------------------------ fonts (Next.js next/font) */

function layoutFile(prof) {
  for (const d of ['app', 'src/app']) for (const f of ['layout.tsx', 'layout.jsx', 'layout.js']) {
    const p = path.join(prof.root, d, f);
    if (fs.existsSync(p)) return path.relative(prof.root, p).split(path.sep).join('/');
  }
  return null;
}

/** The layout's next/font/google setup: { file, fonts: [{ name, callee, variable, start, end }] } */
export function readFonts(prof) {
  const rel = layoutFile(prof);
  if (!rel) return null;
  const code = fs.readFileSync(path.join(prof.root, rel), 'utf8');
  const ast = parse(rel, code);
  const imported = new Map();
  let imp = null;
  for (const st of ast.program.body) {
    if (st.type === 'ImportDeclaration' && st.source.value === 'next/font/google') {
      imp = st;
      for (const sp of st.specifiers) imported.set(sp.local.name, sp.imported ? sp.imported.name : sp.local.name);
    }
  }
  if (!imp) return { file: rel, fonts: [], code };
  const fonts = [];
  walk(ast, (n) => {
    if (n.type === 'VariableDeclarator' && n.init && n.init.type === 'CallExpression' && n.init.callee.type === 'Identifier' && imported.has(n.init.callee.name)) {
      const opts = n.init.arguments[0];
      const vp = opts && opts.type === 'ObjectExpression' ? opts.properties.find((p) => p.key && (p.key.name || p.key.value) === 'variable') : null;
      fonts.push({ name: n.id.name, callee: imported.get(n.init.callee.name), variable: vp && vp.value.type === 'StringLiteral' ? vp.value.value : null });
    }
    return true;
  });
  return { file: rel, fonts, code };
}

const roleOf = (f) => (/heading|display|serif/i.test(f.variable || '') ? 'heading' : /mono|code/i.test(f.variable || f.callee) ? 'mono' : 'body');

/** Rewrite the body / heading next/font families (AST-exact). Returns the new layout source or null. */
export function rewriteFonts(prof, { body, heading } = {}) {
  const info = readFonts(prof);
  if (!info || !info.fonts.length) return null;
  let code = info.code;
  const ast = parse(info.file, code);
  const edits = [];
  const want = { body: body && FONTS.find((f) => f.id === body), heading: heading && FONTS.find((f) => f.id === heading) };
  let imp = null;
  for (const st of ast.program.body) if (st.type === 'ImportDeclaration' && st.source.value === 'next/font/google') imp = st;
  const names = new Set(imp.specifiers.map((s) => (s.imported ? s.imported.name : s.local.name)));
  let hasHeading = false;
  walk(ast, (n) => {
    if (n.type !== 'VariableDeclarator' || !n.init || n.init.type !== 'CallExpression' || n.init.callee.type !== 'Identifier' || !names.has(n.init.callee.name)) return true;
    const opts = n.init.arguments[0];
    const vp = opts && opts.type === 'ObjectExpression' ? opts.properties.find((p) => p.key && (p.key.name || p.key.value) === 'variable') : null;
    const role = roleOf({ variable: vp && vp.value.value, callee: n.init.callee.name });
    if (role === 'heading') hasHeading = true;
    const f = want[role];
    if (!f) return true;
    edits.push({ start: n.init.callee.start, end: n.init.callee.end, text: f.id });
    names.add(f.id);
    const wp = opts && opts.type === 'ObjectExpression' ? opts.properties.find((p) => p.key && (p.key.name || p.key.value) === 'weight') : null;
    if (f.weight && !wp && opts) edits.push({ start: opts.end - 1, end: opts.end - 1, text: `${opts.properties.length ? ', ' : ''}weight: "${f.weight}"` });
    if (!f.weight && wp) {
      const i = opts.properties.indexOf(wp);
      const from = i > 0 ? opts.properties[i - 1].end : wp.start, to = i > 0 ? wp.end : (opts.properties[1] ? opts.properties[1].start : wp.end);
      edits.push({ start: from, end: to, text: '' });
    }
    return true;
  });
  if (want.heading && !hasHeading) {
    // a heading font the layout does not have yet: declared after the imports, exposed as --font-heading on <body>
    const last = ast.program.body.filter((s) => s.type === 'ImportDeclaration').pop();
    edits.push({ start: last.end, end: last.end, text: `\n\nconst fontHeading = ${want.heading.id}({ variable: "--font-heading", subsets: ["latin"]${want.heading.weight ? `, weight: "${want.heading.weight}"` : ''} });` });
    names.add(want.heading.id);
    // the element that already carries the font variables (<html> in create-next-app 16, <body> in older ones)
    let body = null;
    walk(ast, (n) => {
      if (!body && n.type === 'JSXElement' && /^(html|body)$/.test(n.openingElement.name.name || '')) {
        const c = n.openingElement.attributes.find((a) => a.name && a.name.name === 'className');
        if (c && /\.variable\b/.test(code.slice(c.start, c.end))) body = n;
      }
      return !body;
    });
    if (!body) walk(ast, (n) => { if (!body && n.type === 'JSXElement' && n.openingElement.name.name === 'body') body = n; return !body; });
    const cls = body && body.openingElement.attributes.find((a) => a.name && a.name.name === 'className');
    if (cls && cls.value.type === 'StringLiteral') edits.push({ start: cls.value.start, end: cls.value.end, text: `{\`\${fontHeading.variable} ${cls.value.value}\`}` });
    else if (cls && cls.value.type === 'JSXExpressionContainer' && cls.value.expression.type === 'TemplateLiteral') edits.push({ start: cls.value.expression.start + 1, end: cls.value.expression.start + 1, text: '${fontHeading.variable} ' });
    else if (body && !cls) edits.push({ start: body.openingElement.name.end, end: body.openingElement.name.end, text: ' className={fontHeading.variable}' });
  }
  // the import lists exactly the families still used
  const used = new Set();
  const all = code;
  edits.sort((a, b) => b.start - a.start);
  for (const e of edits) code = code.slice(0, e.start) + e.text + code.slice(e.end);
  const ast2 = parse(info.file, code);
  walk(ast2, (n) => { if (n.type === 'CallExpression' && n.callee.type === 'Identifier' && names.has(n.callee.name)) used.add(n.callee.name); return true; });
  const imp2 = ast2.program.body.find((s) => s.type === 'ImportDeclaration' && s.source.value === 'next/font/google');
  code = code.slice(0, imp2.start) + `import { ${[...used].sort().join(', ')} } from "next/font/google";` + code.slice(imp2.end);
  parse(info.file, code);
  void all;
  return { file: info.file, code };
}


/* ------------------------------------------------------------------ state · apply · undo */

const stateDir = (root) => path.join(root, '.deckhand', 'tryon', 'theme');
// every apply keeps the files it replaced: Undo walks back one apply at a time, to the original (10 kept)
const HISTORY_MAX = 10;
function history(root) {
  const d = stateDir(root);
  try { const h = JSON.parse(fs.readFileSync(path.join(d, 'history.json'), 'utf8')); if (Array.isArray(h)) return h; } catch { /* none yet */ }
  try { return [JSON.parse(fs.readFileSync(path.join(d, 'last.json'), 'utf8'))]; } catch { return []; }   // a 2.2.x single undo
}
function saveHistory(root, h) {
  const d = stateDir(root);
  fs.mkdirSync(d, { recursive: true });
  fs.rmSync(path.join(d, 'last.json'), { force: true });
  if (h.length) fs.writeFileSync(path.join(d, 'history.json'), JSON.stringify(h));
  else fs.rmSync(path.join(d, 'history.json'), { force: true });
}

export function themeState(rootIn) {
  const prof = detectProject(rootIn);
  const css = prof.globalsCss ? fs.readFileSync(path.join(prof.root, prof.globalsCss), 'utf8') : '';
  const m = /\/\* dh:theme[^\n]*\n\/\* (\{.*\}) \*\//.exec(css);
  const fonts = prof.framework === 'next' ? readFonts(prof) : null;
  return {
    current: m ? JSON.parse(m[1]) : {}, knobs: { accent: KNOBS.accent, neutrals: KNOBS.neutrals, corners: Object.keys(KNOBS.corners), density: Object.keys(KNOBS.density), headlines: Object.keys(KNOBS.headlines) },
    accents: ACCENTS, fonts: fonts && fonts.fonts.length ? { list: FONTS, layout: fonts.file, current: fonts.fonts.map((f) => ({ callee: f.callee, variable: f.variable, role: roleOf(f) })) } : null,
    spacingVar: prof.tailwind === 4, css: prof.globalsCss, undo: history(prof.root).length > 0, undoSteps: history(prof.root).length,
  };
}

export function themeApply(rootIn, vIn = {}) {
  const v = cleanTheme(vIn);
  const prof = detectProject(rootIn);
  if (!prof.globalsCss) throw Object.assign(new Error('no global stylesheet found (app/globals.css, src/index.css…)'), { code: 'NO_GLOBALS_CSS' });
  const cssPath = path.join(prof.root, prof.globalsCss);
  const before = { [prof.globalsCss]: fs.readFileSync(cssPath, 'utf8') };
  let css = stripBlock(before[prof.globalsCss]);
  let fonts = null, bodyVar = null;
  if ((v.body || v.heading) && prof.framework === 'next') {
    const info = readFonts(prof);
    const bodyDecl = info && info.fonts.find((f) => roleOf(f) === 'body' && f.variable);
    bodyVar = v.body && bodyDecl ? bodyDecl.variable : null;
    fonts = rewriteFonts(prof, { body: v.body, heading: v.heading });
    if (fonts) before[fonts.file] = fs.readFileSync(path.join(prof.root, fonts.file), 'utf8');
  }
  const block = themeCss(v, { bodyVar, heading: !!(fonts && v.heading) });
  css = css.replace(/\s*$/, '\n') + (block ? '\n' + block : '');
  fs.writeFileSync(cssPath, css);
  if (fonts) fs.writeFileSync(path.join(prof.root, fonts.file), fonts.code);
  const after = Object.fromEntries(Object.keys(before).map((rel) => [rel, shaText(fs.readFileSync(path.join(prof.root, rel), 'utf8'))]));
  saveHistory(prof.root, history(prof.root).concat([{ at: new Date().toISOString(), files: before, after }]).slice(-HISTORY_MAX));
  return { applied: v, files: [prof.globalsCss, ...(fonts ? [fonts.file] : [])], vars: themeVars(v) };
}

const shaText = (s) => crypto.createHash('sha256').update(s).digest('hex');

export function themeUndo(rootIn, { force = false } = {}) {
  const prof = detectProject(rootIn);
  const h = history(prof.root);
  if (!h.length) throw Object.assign(new Error('nothing to undo'), { code: 'NO_UNDO' });
  const last = h[h.length - 1];
  // byte-exact means back to before the apply: a file edited since would lose that edit, so it is the owner's call
  const cur = (rel) => { try { return shaText(fs.readFileSync(path.join(prof.root, rel), 'utf8')); } catch { return null; } };
  const edited = Object.keys(last.after || {}).filter((rel) => cur(rel) !== last.after[rel]);
  if (edited.length && !force) {
    throw Object.assign(new Error(`edited since the theme was applied: ${edited.join(', ')} — undo would lose those edits (theme --undo --force to undo anyway)`), { code: 'FILE_CHANGED', files: edited });
  }
  h.pop();
  for (const [rel, text] of Object.entries(last.files)) fs.writeFileSync(path.join(prof.root, rel), text);
  saveHistory(prof.root, h);
  return { restored: Object.keys(last.files), mode: 'byte-exact', more: h.length };
}
