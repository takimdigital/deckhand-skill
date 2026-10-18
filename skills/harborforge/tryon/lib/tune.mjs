/**
 * tune.mjs — adjust a picked element's design with knobs, not prompts (zero model calls).
 *
 * Every knob is a deterministic Tailwind class transform applied to the element's subtree in its own file:
 *   density  -2..+2   spacing (p/m/gap/space-*) × 0.6 · 0.8 · 1 · 1.25 · 1.5
 *   size     -2..+2   text sizes: headline sizes move a full step per notch, body sizes half as much
 *   weight   -2..+2   font weights (existing ones), clamped light..black
 *   corners  sharp · soft · · round · pill   rounded-* (rounded-full circles are left alone except by sharp)
 *   depth    flat · subtle · · raised        shadow-* ; raised gives bordered cards a lift
 *   contrast soft · · crisp                  muted text ↔ foreground, faint borders ↔ full borders
 *   width    -2..+2   max-w-* steps
 * Presets (the Impeccable verbs, as knob combinations): quieter, bolder, airy, compact, clarity, softer, sharper.
 * A tune session always recomputes from the ORIGINAL source (never cumulative drift) and writes it; the dev
 * server's HMR shows it — so what you see is exactly what you keep. Reset restores the file byte-exact.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { detectProject } from './project.mjs';
import { pickElement, styledBy } from './engine.mjs';

const require = createRequire(import.meta.url);
const { parse, walk, findElementAt, jsxName, lineCol } = require('./ast.cjs');

export const PRESETS = {
  quieter: { density: 1, size: -1, weight: -1, depth: 'flat', contrast: 'soft' },
  bolder: { size: 1, weight: 1, contrast: 'crisp', depth: 'raised' },
  airy: { density: 2 },
  compact: { density: -1, size: -1 },
  clarity: { contrast: 'crisp', weight: 1 },
  softer: { corners: 'round', depth: 'subtle' },
  sharper: { corners: 'sharp', depth: 'flat' },
};
export const DIALS = {
  density: { kind: 'step', min: -2, max: 2, labels: ['compact', 'snug', 'as is', 'airy', 'spacious'] },
  size: { kind: 'step', min: -2, max: 2, labels: ['smaller', 'small', 'as is', 'larger', 'display'] },
  weight: { kind: 'step', min: -2, max: 2, labels: ['light', 'lighter', 'as is', 'bolder', 'heavy'] },
  corners: { kind: 'choice', options: ['sharp', 'soft', 'as is', 'round', 'pill'] },
  depth: { kind: 'choice', options: ['flat', 'subtle', 'as is', 'raised'] },
  contrast: { kind: 'choice', options: ['soft', 'as is', 'crisp'] },
  width: { kind: 'step', min: -2, max: 2, labels: ['narrow', 'narrower', 'as is', 'wider', 'wide'] },
};

const DENSITY = [0.6, 0.8, 1, 1.25, 1.5];
const SIZES = ['xs', 'sm', 'base', 'lg', 'xl', '2xl', '3xl', '4xl', '5xl', '6xl', '7xl', '8xl', '9xl'];
const WEIGHTS = ['thin', 'extralight', 'light', 'normal', 'medium', 'semibold', 'bold', 'extrabold', 'black'];
const RADII = ['none', 'sm', '', 'md', 'lg', 'xl', '2xl', '3xl'];
const SHADOWS = ['none', '2xs', 'xs', 'sm', '', 'md', 'lg', 'xl', '2xl'];
const WIDTHS = ['xs', 'sm', 'md', 'lg', 'xl', '2xl', '3xl', '4xl', '5xl', '6xl', '7xl'];
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const num = (n) => (Number.isInteger(n) ? String(n) : String(n));

/** One class token (with its variant prefixes, e.g. `md:hover:`) → the tuned token(s). */
export function tuneToken(tok, d, ctx = {}) {
  const m = /^((?:[\w-]+(?:\[[^\]]*\])?:)*)(!?)(.*)$/.exec(tok);
  const pre = m[1] + m[2];
  let c = m[3];
  if (d.density) {
    const s = /^(-?)(p|px|py|pt|pr|pb|pl|ps|pe|m|mx|my|mt|mr|mb|ml|gap|gap-x|gap-y|space-x|space-y)-(\d+(?:\.5)?)$/.exec(c);
    if (s) {
      const n = Number(s[3]) * DENSITY[clamp(d.density, -2, 2) + 2];
      const r = n < 4 ? Math.round(n * 2) / 2 : Math.round(n);
      c = `${s[1]}${s[2]}-${num(r)}`;
    }
  }
  if (d.size) {
    const s = /^text-(xs|sm|base|lg|[2-9]?xl)$/.exec(c);
    if (s) {
      const i = SIZES.indexOf(s[1]);
      const k = i >= SIZES.indexOf('xl') ? d.size : Math.trunc(d.size / 2);
      c = 'text-' + SIZES[clamp(i + k, 0, SIZES.length - 1)];
    }
  }
  if (d.weight) {
    const s = /^font-(thin|extralight|light|normal|medium|semibold|bold|extrabold|black)$/.exec(c);
    if (s) c = 'font-' + WEIGHTS[clamp(WEIGHTS.indexOf(s[1]) + d.weight, 2, WEIGHTS.length - 1)];
  }
  if (d.corners && d.corners !== 'as is') {
    const s = /^rounded(-(t|b|l|r|tl|tr|bl|br|s|e|ss|se|es|ee))?(?:-(none|sm|md|lg|xl|2xl|3xl|full))?$/.exec(c);
    if (s) {
      const side = s[1] || '', cur = s[3] || '';
      if (cur === 'full') { if (d.corners === 'sharp') c = `rounded${side}-none`; }
      else {
        const i = RADII.indexOf(cur);
        const to = d.corners === 'sharp' ? 'none' : d.corners === 'soft' ? (i > 3 ? 'md' : cur || '') : d.corners === 'round' ? RADII[clamp(i + 2, 0, RADII.length - 1)]
          : ctx.control ? 'full' : RADII[clamp(i + 3, 0, RADII.length - 1)];
        c = `rounded${side}${to ? '-' + to : ''}`;
      }
    }
  }
  if (d.depth && d.depth !== 'as is') {
    const s = /^shadow(?:-(none|2xs|xs|sm|md|lg|xl|2xl))?$/.exec(c);
    if (s) {
      const i = SHADOWS.indexOf(s[1] || '');
      c = d.depth === 'flat' ? 'shadow-none' : d.depth === 'subtle' ? 'shadow-sm' : 'shadow-' + SHADOWS[clamp(Math.max(i, 3) + 2, 0, SHADOWS.length - 1)];
    }
  }
  if (d.contrast === 'crisp') {
    if (c === 'text-muted-foreground') c = 'text-foreground/80';
    else if (/^border-(border|input)\/\d+$/.test(c)) c = c.replace(/\/\d+$/, '');
  } else if (d.contrast === 'soft') {
    if (/^text-foreground\/\d+$/.test(c) && !ctx.heading) c = 'text-muted-foreground';
  }
  if (d.width) {
    const s = /^max-w-(xs|sm|md|lg|xl|[2-7]xl)$/.exec(c);
    if (s) c = 'max-w-' + WIDTHS[clamp(WIDTHS.indexOf(s[1]) + d.width, 0, WIDTHS.length - 1)];
  }
  return pre + c;
}

/** A whole class string; `raised` adds a lift to bordered, rounded cards that had no shadow. */
export function tuneClassList(list, d, ctx = {}) {
  const toks = list.split(/(\s+)/);
  const out = toks.map((t) => (/^\s*$/.test(t) ? t : tuneToken(t, d, ctx)));
  let s = out.join('');
  const words = s.split(/\s+/).filter(Boolean);
  if (d.depth === 'raised' && ctx.card && !words.some((w) => /(^|:)shadow(-|$)/.test(w))) s = s.replace(/\s*$/, (sp) => ' shadow-md' + sp);
  return s;
}

const isControl = (name) => /^(button|a|Button|Link)$/.test(name);

/** Classes a knob sets on the picked control when it has none of that family yet. */
function addMissing(list, d, ctx) {
  const w = list.split(/\s+/).filter(Boolean);
  const has = (rx) => w.some((x) => rx.test(x.replace(/^(?:[\w-]+(?:\[[^\]]*\])?:)*!?/, '')));
  const add = [];
  if (d.corners && d.corners !== 'as is' && !has(/^rounded(-|$)/)) add.push({ sharp: 'rounded-none', soft: 'rounded-md', round: 'rounded-xl', pill: 'rounded-full' }[d.corners]);
  if (d.depth && d.depth !== 'as is' && !has(/^shadow(-|$)/)) add.push({ flat: 'shadow-none', subtle: 'shadow-sm', raised: 'shadow-md' }[d.depth]);
  if (d.weight && !has(/^font-(thin|extralight|light|normal|medium|semibold|bold|extrabold|black)$/)) add.push(['font-light', 'font-normal', null, 'font-semibold', 'font-bold'][clamp(d.weight, -2, 2) + 2]);
  if (d.size && ctx.control && !has(/^text-(xs|sm|base|lg|[2-9]?xl)$/)) add.push(['text-xs', 'text-xs', null, 'text-base', 'text-lg'][clamp(d.size, -2, 2) + 2]);
  const extra = add.filter(Boolean);
  return extra.length ? (list.trim() ? list.replace(/\s*$/, ' ' + extra.join(' ')) : extra.join(' ')) : list;
}
const isHeading = (name) => /^h[1-6]$/.test(name);

/** Transform every class string inside `el` (className literals, template quasis, cn()/clsx() strings). */
export function tuneElement(code, el, d) {
  const edits = [];
  walk(el, (n) => {
    if (n.type !== 'JSXElement') return true;
    const name = jsxName(n.openingElement.name);
    const attr = n.openingElement.attributes.find((a) => a.type === 'JSXAttribute' && a.name && /^(className|class)$/.test(a.name.name));
    if (!attr || !attr.value) return true;
    const raw = attr.value.type === 'StringLiteral' ? attr.value.value : '';
    const ctx = { control: isControl(name), heading: isHeading(name), card: /\bborder\b/.test(raw) && /\brounded/.test(raw) };
    const strings = [];
    if (attr.value.type === 'StringLiteral') strings.push(attr.value);
    else walk(attr.value, (x) => {
      if (x.type === 'StringLiteral') strings.push(x);
      if (x.type === 'TemplateElement') strings.push(x);
      return true;
    });
    for (const s of strings) {
      if (s.type === 'TemplateElement') {
        const v = s.value.raw;
        const t = tuneClassList(v, d, ctx);
        if (t !== v) edits.push({ start: s.start, end: s.end, text: t });
      } else {
        let t = tuneClassList(s.value, d, ctx);
        // the picked button/component itself: a knob with nothing to transform ADDS its class (a shadcn <Button>
        // gets its corners from ui/button.tsx; a class on the usage wins through cn/tailwind-merge)
        if (n === el && attr.value === s && (ctx.control || /^[A-Z]/.test(name))) t = addMissing(t, d, ctx);
        if (t !== s.value) edits.push({ start: s.start + 1, end: s.end - 1, text: t });
      }
    }
    return true;
  });
  edits.sort((a, b) => b.start - a.start);
  let out = code;
  for (const e of edits) out = out.slice(0, e.start) + e.text + out.slice(e.end);
  return { code: out, changed: edits.length };
}

/** Preset + dials, validated: known dials only, steps are integers in range, choices from their list (BAD_DIAL). */
export function dialsOf(dials = {}, preset = null) {
  const bad = (m) => Object.assign(new Error(m), { code: 'BAD_DIAL' });
  if (preset != null && preset !== '' && !PRESETS[preset]) throw bad(`preset: ${Object.keys(PRESETS).join(', ')}`);
  const merged = { ...(preset ? PRESETS[preset] : {}), ...(dials || {}) };
  const out = {};
  for (const [k, v] of Object.entries(merged)) {
    const spec = DIALS[k];
    if (!spec) throw bad(`unknown dial "${k}" (${Object.keys(DIALS).join(', ')})`);
    if (spec.kind === 'step') {
      const n = Number(v);
      if (!Number.isInteger(n) || n < spec.min || n > spec.max) throw bad(`${k}: an integer from ${spec.min} to ${spec.max}`);
      out[k] = n;
    } else {
      if (!spec.options.includes(v)) throw bad(`${k}: ${spec.options.join(', ')}`);
      out[k] = v;
    }
  }
  return out;
}

/* ------------------------------------------------------------------ sessions (file-level, reversible) */

const dir = (root) => path.join(root, '.deckhand', 'tryon', 'tune');
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');
const load = (root, id) => {
  if (!/^[A-Za-z0-9_-]{1,40}$/.test(String(id))) throw Object.assign(new Error('bad tune session id'), { code: 'BAD_ID' });
  const p = path.join(dir(root), id + '.json');
  if (!fs.existsSync(p)) throw Object.assign(new Error('no tune session ' + id), { code: 'NO_TUNE' });
  return JSON.parse(fs.readFileSync(p, 'utf8'));
};
const save = (root, s) => { fs.mkdirSync(dir(root), { recursive: true }); fs.writeFileSync(path.join(dir(root), s.id + '.json'), JSON.stringify(s, null, 1)); };

export function tuneOpen(rootIn, { file, line, col, hint }) {
  const root = detectProject(rootIn).root;
  const rel = String(file).replace(/\\/g, '/');
  const abs = path.resolve(root, rel);
  if (!abs.startsWith(root + path.sep)) throw Object.assign(new Error(rel + ' is outside the project'), { code: 'OUTSIDE_PROJECT' });
  if (/(^|\/)(node_modules|\.next|dist|build)\//.test(rel)) throw Object.assign(new Error(rel + ' is generated/vendored — pick the element in your source'), { code: 'GENERATED_FILE' });
  const code = fs.readFileSync(abs, 'utf8');
  const ast = parse(rel, code);
  const picked = pickElement(ast, code, line, col, hint);
  // a Link inside <Button asChild>: the knobs act on the Button (its classes make the button)
  const el = picked && styledBy(ast, picked.el);
  if (el) { const lc = lineCol(code, el.start); line = lc.line; col = lc.col; }
  if (!el) throw Object.assign(new Error(`no JSX element at ${rel}:${line}:${col} — the page is older than the file: reload it and pick again`), { code: 'ELEMENT_NOT_FOUND', reload: true });
  const id = 't' + Date.now().toString(36).slice(-6);
  fs.mkdirSync(dir(root), { recursive: true });
  fs.writeFileSync(path.join(dir(root), id + '.orig'), code);
  const s = { id, state: 'open', file: rel, line: Number(line), col: Number(col), dials: {}, shaOrig: sha(code), shaNow: sha(code), tag: jsxName(el.openingElement.name) };
  save(root, s);
  return { id, file: rel, tag: s.tag, dials: DIALS, presets: Object.keys(PRESETS) };
}

export function tuneSet(rootIn, id, { dials = {}, preset = null } = {}) {
  const root = detectProject(rootIn).root;
  const s = load(root, id);
  if (s.state !== 'open') throw Object.assign(new Error('tune session ' + id + ' is ' + s.state), { code: 'TUNE_CLOSED' });
  const abs = path.join(root, s.file);
  if (sha(fs.readFileSync(abs)) !== s.shaNow) throw Object.assign(new Error(s.file + ' changed since tuning started — keep or reset first'), { code: 'FILE_CHANGED' });
  const orig = fs.readFileSync(path.join(dir(root), id + '.orig'), 'utf8');
  const el = findElementAt(parse(s.file, orig), orig, s.line, s.col);
  const d = dialsOf(dials, preset);
  const r = tuneElement(orig, el, d);
  parse(s.file, r.code);                                            // never write unparseable source
  fs.writeFileSync(abs, r.code);
  s.dials = d; s.shaNow = sha(r.code);
  save(root, s);
  return { id, dials: d, changed: r.changed };
}

const mustBeOpen = (s) => { if (s.state !== 'open') throw Object.assign(new Error('tune session ' + s.id + ' is ' + s.state), { code: 'TUNE_CLOSED' }); };

export function tuneKeep(rootIn, id) {
  const root = detectProject(rootIn).root;
  const s = load(root, id);
  mustBeOpen(s);
  s.state = 'kept';
  save(root, s);
  fs.rmSync(path.join(dir(root), id + '.orig'), { force: true });
  return { id, kept: s.dials, file: s.file };
}

export function tuneReset(rootIn, id) {
  const root = detectProject(rootIn).root;
  const s = load(root, id);
  mustBeOpen(s);
  const abs = path.join(root, s.file);
  const orig = fs.readFileSync(path.join(dir(root), id + '.orig'));
  let out = { id, restored: s.file, mode: 'byte-exact' };
  if (sha(fs.readFileSync(abs)) !== s.shaNow) {
    // the owner edited the file meanwhile: put back only the class strings the knobs changed, keep every edit of theirs
    const o = orig.toString('utf8');
    const tuned = tuneElement(o, findElementAt(parse(s.file, o), o, s.line, s.col), s.dials || {}).code;
    let cur = fs.readFileSync(abs, 'utf8');
    let undone = 0, left = 0;
    for (const [from, to] of classPairs(s.file, tuned, o)) {
      const n = cur.split(from).length - 1;
      if (n === 1) { cur = cur.replace(from, () => to); undone++; } else left++;
    }
    parse(s.file, cur);                                            // never write unparseable source
    fs.writeFileSync(abs, cur);
    out = { id, restored: s.file, mode: 'surgical (your edits kept)', undone, ...(left ? { left, note: `${left} class change(s) could not be matched — check ${s.file}` } : {}) };
  } else fs.writeFileSync(abs, orig);
  s.state = 'reset';
  save(root, s);
  fs.rmSync(path.join(dir(root), id + '.orig'), { force: true });
  return out;
}

/** The class attributes a tune rewrote: [tuned source, original source] pairs, in document order. */
function classPairs(file, tuned, orig) {
  const attrs = (code) => {
    const out = [];
    walk(parse(file, code), (n) => {
      if (n.type === 'JSXAttribute' && n.name && /^(className|class)$/.test(n.name.name) && n.value) out.push(code.slice(n.value.start, n.value.end));
      return true;
    });
    return out;
  };
  const a = attrs(tuned), b = attrs(orig);
  if (a.length !== b.length) return [];
  return a.map((t, i) => [t, b[i]]).filter(([t, o]) => t !== o);
}
