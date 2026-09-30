/**
 * materialize.mjs — turn a catalog item into files inside the project, self-contained:
 *
 *   <componentsDir>/dh-tryon/<slug>/<slug>.tsx     the entry component
 *   <componentsDir>/dh-tryon/<slug>/<helper>.tsx   every file it needs that the project lacks
 *
 * Rules (the reason v1 swaps broke at import time):
 *  - EVERY file the item needs is fetched (v1 staged only the entry file);
 *  - a ui primitive the project already has (button, card, input…) is NOT fetched: the import is
 *    pointed at the project's own component, so the variant renders in the site's design system;
 *  - `lib/utils` resolves to the project's cn(); a project without one gets a local copy;
 *  - bare imports become npm deps (reported; installed by the caller, batched);
 *  - palette classes -> semantic tokens; 'use client' added when hooks/handlers need it;
 *  - an attribution header (source URL + licence) is written into every file.
 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { followGh, fetchJsonItem, importsOf, pkgName, getText } from './registry.mjs';
import { normalizeClasses } from './theme.mjs';
import { specFor, depInstalled } from './project.mjs';
import { libraryDir } from './catalog.mjs';

const require = createRequire(import.meta.url);
const { parse, walk } = require('./ast.cjs');

const UTILS_SRC = `import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
`;
const BUILTIN = new Set(['react', 'react-dom', 'next']);

/**
 * A design written for Next (`next/link`, `next/image`) in a Vite/CRA project: a local stand-in with the same props,
 * so the design renders instead of failing to import. Next projects never get these.
 */
const NEXT_SHIMS = {
  'next/link': ['next-link.tsx', `import * as React from "react"

/** Stand-in for next/link outside Next (written by deckhand try-on): a plain anchor. */
export default function Link({ href, prefetch, replace, scroll, shallow, locale, legacyBehavior, passHref, ...rest }: any) {
  const to = typeof href === "string" ? href : (href && (href.pathname || "")) + (href && href.hash ? "#" + href.hash : "")
  return <a href={to || "#"} {...rest} />
}
`],
  'next/image': ['next-image.tsx', `import * as React from "react"

/** Stand-in for next/image outside Next (written by deckhand try-on): a plain img with the same props. */
export default function Image({ src, alt, width, height, fill, priority, unoptimized, quality, placeholder, blurDataURL, loader, sizes, style, ...rest }: any) {
  const url = typeof src === "string" ? src : src && src.src
  const box = fill ? { position: "absolute", inset: 0, width: "100%", height: "100%", ...(style || {}) } : style
  return <img src={url} alt={alt ?? ""} width={fill ? undefined : width} height={fill ? undefined : height} loading={priority ? "eager" : "lazy"} style={box} {...rest} />
}
`],
};

export const slugOf = (item) => (item.r + '-' + item.n).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 64);
export const pascal = (s) => s.replace(/(^|[^a-zA-Z0-9]+)([a-zA-Z0-9])/g, (_, __, c) => c.toUpperCase()).replace(/^[0-9]/, 'C$&');

/** Which import specs the project satisfies itself. Returns the replacement spec, or null. */
function projectProvides(prof, spec) {
  const ui = /(?:^|\/)ui\/([a-z0-9-]+)$/.exec(spec);
  if (ui && (spec.startsWith('@/') || spec.startsWith('~/')) && prof.ui[ui[1]]) return specFor(prof, prof.ui[ui[1]]);
  if (/(?:^|\/)lib\/utils$/.test(spec) && (spec.startsWith('@/') || spec.startsWith('~/')) && prof.utilsExists) {
    return specFor(prof, prof.utilsFile);
  }
  return null;
}

/**
 * HTML-spelled attributes on host elements, as React spells them (`flood-opacity` → `floodOpacity`,
 * `xlink:href` → `xlinkHref`): a design pasted from an SVG editor renders, but floods the console with
 * "Invalid DOM property" warnings, which the overlay's auto-check reads as errors. `data-*` and `aria-*` stay.
 */
export function reactAttrs(file, code) {
  let ast;
  try { ast = parse(file, code); } catch { return code; }
  const edits = [];
  walk(ast, (n) => {
    if (n.type !== 'JSXOpeningElement' || n.name.type !== 'JSXIdentifier' || !/^[a-z][a-zA-Z0-9]*$/.test(n.name.name)) return true;   // a host tag; a custom element (`<my-el>`) takes attributes as written
    for (const a of n.attributes) {
      const nm = a.type === 'JSXAttribute' ? a.name : null;
      let from = null;
      if (nm && nm.type === 'JSXIdentifier' && nm.name.includes('-') && !/^(data|aria)-/.test(nm.name)) from = nm.name;
      else if (nm && nm.type === 'JSXNamespacedName') from = nm.namespace.name + '-' + nm.name.name;
      if (from) edits.push({ start: nm.start, end: nm.end, text: from.replace(/-([a-z])/g, (_, c) => c.toUpperCase()) });
    }
    return true;
  });
  edits.sort((a, b) => b.start - a.start);
  for (const e of edits) code = code.slice(0, e.start) + e.text + code.slice(e.end);
  return code;
}

/** Upstream typing bugs fixed deterministically so a kept file passes `next build` type checks. */
export function compatFixes(file, code) {
  let ast;
  try { ast = parse(file, code); } catch { return code; }
  const edits = [];
  const imgImport = ast.program.body.find((st) => st.type === 'ImportDeclaration' && st.source.value === 'next/image');
  const imageLocal = imgImport && imgImport.specifiers.find((x) => x.type === 'ImportDefaultSpecifier')?.local.name;
  walk(ast, (n) => {
    // next/image in a staged file: `unoptimized`, so a demo's remote host can never crash the page
    // ("hostname … is not configured under images") — the owner's own images keep their config
    if (n.type === 'JSXOpeningElement' && n.name.type === 'JSXIdentifier' && n.name.name === imageLocal
      && !n.attributes.some((a) => a.type === 'JSXAttribute' && a.name.name === 'unoptimized')) {
      edits.push({ at: n.name.end, text: ' unoptimized' });
    }
    // `(React.)ComponentProps` used bare: infer the element from what the component returns
    // (a TS function TYPE — `onChange: (v: string) => void` — is a Function node without `params`)
    if (/Function/.test(n.type) && Array.isArray(n.params) && n.params[0] && n.params[0].typeAnnotation) {
      const ta = n.params[0].typeAnnotation.typeAnnotation;
      const tn = ta && ta.type === 'TSTypeReference' ? code.slice(ta.typeName.start, ta.typeName.end) : '';
      if (/^(React\.)?(ComponentProps|ComponentPropsWithoutRef|ComponentPropsWithRef)$/.test(tn) && !ta.typeParameters && !ta.typeArguments) {
        // the element that receives `{...props}` owns the props type; else the first element returned
        const pat = n.params[0].type === 'ObjectPattern' ? n.params[0] : null;
        const rest = pat && pat.properties.find((x) => x.type === 'RestElement');
        const restName = rest ? rest.argument.name : (n.params[0].type === 'Identifier' ? n.params[0].name : null);
        let el = null, first = null;
        walk(n.body, (m) => {
          if (el) return false;
          if (m.type === 'JSXOpeningElement') {
            if (!first) first = code.slice(m.name.start, m.name.end);
            if (restName && m.attributes.some((at) => at.type === 'JSXSpreadAttribute' && at.argument.type === 'Identifier' && at.argument.name === restName)) {
              el = code.slice(m.name.start, m.name.end);
              return false;
            }
          }
          return true;
        });
        el = el || first;
        if (el) edits.push({ at: ta.typeName.end, text: /^[a-z]/.test(el) && !el.includes('.') ? `<"${el}">` : `<typeof ${el}>` });
      }
    }
    // `SVGProps` used bare (React 19 types require the element parameter)
    if (n.type === 'TSTypeReference' && n.typeName.type === 'Identifier' && n.typeName.name === 'SVGProps' && !n.typeParameters && !n.typeArguments) {
      edits.push({ at: n.typeName.end, text: '<SVGSVGElement>' });
    }
    return true;
  });
  edits.sort((a, b) => b.at - a.at);
  for (const e of edits) code = code.slice(0, e.at) + e.text + code.slice(e.at);
  return code;
}

/**
 * What the project's own ui component accepts of the cva props a design passes (`variant`, `size`…), per export:
 * Map(name → Map(prop → Set(values) | null = any value)). Read from the project's file (shadcn: `cva(…, { variants })`
 * + `VariantProps<typeof x>` or a destructured prop).
 */
const variantCache = new Map();
function projectVariants(abs) {
  if (variantCache.has(abs)) return variantCache.get(abs);
  const out = new Map();
  let code = '', ast;
  try { code = fs.readFileSync(abs, 'utf8'); ast = parse(abs, code); } catch { variantCache.set(abs, null); return null; }
  const cvas = new Map();
  walk(ast, (n) => {
    if (n.type === 'VariableDeclarator' && n.id.type === 'Identifier' && n.init && n.init.type === 'CallExpression' && n.init.callee.type === 'Identifier' && n.init.callee.name === 'cva') {
      const cfg = n.init.arguments[1];
      const vs = cfg && cfg.type === 'ObjectExpression' ? cfg.properties.find((p) => p.type === 'ObjectProperty' && (p.key.name || p.key.value) === 'variants') : null;
      const m = new Map();
      if (vs && vs.value.type === 'ObjectExpression') for (const p of vs.value.properties) if (p.type === 'ObjectProperty' && p.value.type === 'ObjectExpression') m.set(p.key.name || p.key.value, new Set(p.value.properties.filter((q) => q.type === 'ObjectProperty').map((q) => String(q.key.name ?? q.key.value))));
      cvas.set(n.id.name, m);
    }
    return true;
  });
  const addFn = (name, fn) => {
    if (!fn || !Array.isArray(fn.params)) return;
    const p0 = fn.params[0];
    const acc = new Map();
    const ann = p0 && p0.typeAnnotation ? code.slice(p0.typeAnnotation.start, p0.typeAnnotation.end) : '';
    for (const [cv, m] of cvas) if (new RegExp(`VariantProps<\\s*typeof\\s+${cv}\\s*>`).test(ann)) for (const [k, v] of m) acc.set(k, v);
    if (p0 && p0.type === 'ObjectPattern') for (const pr of p0.properties) if (pr.type === 'ObjectProperty' && !acc.has(pr.key.name)) acc.set(pr.key.name, null);
    out.set(name, acc);
  };
  walk(ast, (n) => {
    if (n.type === 'FunctionDeclaration' && n.id) addFn(n.id.name, n);
    if (n.type === 'VariableDeclarator' && n.id.type === 'Identifier' && n.init) {
      let i = n.init;
      if (i.type === 'CallExpression' && i.arguments[0] && /Function/.test(i.arguments[0].type)) i = i.arguments[0];
      if (/Function/.test(i.type)) addFn(n.id.name, i);
    }
    return true;
  });
  variantCache.set(abs, out);
  return out;
}

/**
 * A design calls the project's own primitives (reused, not fetched) with the props of ITS registry's version:
 * Veil's `<Card variant="outline">` against a shadcn Card that has no variant — fine in dev, a failed `next build`
 * type check once kept. A variant prop the project's component does not take is dropped; a value it does not have
 * becomes "default" (or is dropped).
 */
export function fitProjectPrimitives(prof, file, code) {
  let ast;
  try { ast = parse(file, code); } catch { return code; }
  const bySpec = new Map();
  for (const [name, rel] of Object.entries(prof.ui || {})) bySpec.set(specFor(prof, rel), path.join(prof.root, rel));
  const locals = new Map();
  for (const st of ast.program.body) {
    if (st.type !== 'ImportDeclaration' || !bySpec.has(st.source.value)) continue;
    for (const sp of st.specifiers) if (sp.type === 'ImportSpecifier') locals.set(sp.local.name, { abs: bySpec.get(st.source.value), name: sp.imported.name || sp.imported.value });
  }
  if (!locals.size) return code;
  const edits = [];
  walk(ast, (n) => {
    if (n.type !== 'JSXOpeningElement' || n.name.type !== 'JSXIdentifier' || !locals.has(n.name.name)) return true;
    const l = locals.get(n.name.name);
    const acc = (projectVariants(l.abs) || new Map()).get(l.name);
    if (!acc) return true;                                           // cannot tell: leave it
    for (const a of n.attributes) {
      if (a.type !== 'JSXAttribute' || !/^(variant|size|tone|intent|shape)$/.test(a.name.name)) continue;
      const lits = [];
      if (a.value && a.value.type === 'StringLiteral') lits.push(a.value);
      else if (a.value && a.value.type === 'JSXExpressionContainer') walk(a.value.expression, (m) => { if (m.type === 'StringLiteral') lits.push(m); return true; });
      const values = acc.get(a.name.name);
      const drop = () => { let st = a.start; while (st > 0 && /\s/.test(code[st - 1])) st--; edits.push({ start: st, end: a.end, text: '' }); };
      if (!acc.has(a.name.name)) { drop(); continue; }
      if (!values) continue;
      const bad = lits.filter((x) => !values.has(x.value));
      if (!bad.length) continue;
      if (values.has('default')) for (const x of bad) edits.push({ start: x.start, end: x.end, text: '"default"' });
      else drop();
    }
    return true;
  });
  if (!edits.length) return code;
  edits.sort((a, b) => b.start - a.start);
  let out = code;
  for (const e of edits) out = out.slice(0, e.start) + e.text + out.slice(e.end);
  try { parse(file, out); } catch { return code; }
  return out;
}

function needsClient(code) {
  if (/^\s*(['"])use client\1/m.test(code.slice(0, 400))) return false;
  return /\buse(State|Effect|Ref|Reducer|Context|LayoutEffect|Transition|Id|Memo|Callback|Scroll|InView|Motion\w*|Animation|Media)\b\s*[(<]/.test(code)
    || /\bon[A-Z][a-zA-Z]+=\{/.test(code) || /from\s+['"](motion\/react|framer-motion)['"]/.test(code)
    || /\bcreateContext\s*\(/.test(code);
}

function exportsOf(file, code) {
  const out = { defaultName: null, hasDefault: false, named: [] };
  let ast;
  try { ast = parse(file, code); } catch { return out; }
  for (const st of ast.program.body) {
    if (st.type === 'ExportDefaultDeclaration') {
      out.hasDefault = true;
      if (st.declaration?.id?.name) out.defaultName = st.declaration.id.name;
      else if (st.declaration?.type === 'Identifier') out.defaultName = st.declaration.name;
    } else if (st.type === 'ExportNamedDeclaration') {
      if (st.declaration?.type === 'FunctionDeclaration' && st.declaration.id) out.named.push(st.declaration.id.name);
      if (st.declaration?.type === 'VariableDeclaration') for (const d of st.declaration.declarations) if (d.id.name) out.named.push(d.id.name);
      for (const s of st.specifiers || []) if (s.exported?.name) out.named.push(s.exported.name === 'default' ? (out.hasDefault = true, 'default') : s.exported.name);
    }
  }
  return out;
}

/**
 * The export a variant usage binds to: default, else the PascalCase named export named like the file (`bento-grid.tsx`
 * exports `{ BentoCard, BentoGrid }`: the container, not its first part), else the first PascalCase named export.
 */
export function entryExport(file, code) {
  const e = exportsOf(file, code);
  if (e.hasDefault) return { kind: 'default', name: e.defaultName };
  const comps = e.named.filter((n) => /^[A-Z]/.test(n));
  const base = path.basename(String(file)).replace(/\.[a-z]+$/i, '').replace(/[^a-z0-9]/gi, '').toLowerCase();
  const byFile = comps.filter((n) => base.endsWith(n.toLowerCase())).sort((a, b) => b.length - a.length)[0];
  const comp = byFile || comps[0];
  return comp ? { kind: 'named', name: comp } : null;
}

/** Fetch (cached) the normalized bundle for a catalog item. */
export async function fetchBundle(prof, item) {
  const errors = [];
  if (item.local || item.draftDir) {
    // a personal-library item (files as the owner kept them) or an AI draft (files as the agent wrote them)
    const dir = item.draftDir || path.join(libraryDir(), 'components', item.local);
    const ns = item.draftDir ? 'ai/' + item.n : 'mine/' + item.local;
    const files = fs.readdirSync(dir).filter((f) => /\.(tsx|ts|jsx|js|css)$/.test(f)).map((f) => ({ path: ns + '/' + f, content: fs.readFileSync(path.join(dir, f), 'utf8').replace(/^\/\* .*? \*\/\n/, '') }));
    const entry = ns + '/' + item.entry;
    const deps = new Set(realPackages(item.deps));
    const external = {};
    for (const f of files) for (const imp of importsOf(f.path, f.content)) {
      const prov = projectProvides(prof, imp.spec);
      if (prov) external[imp.spec] = prov;
    }
    return { origin: item.draftDir ? 'ai' : 'library', sourceUrl: item.source || (item.draftDir ? 'ai-draft:' + item.n : 'library:' + item.local), entry, files, deps: [...deps], external, css: null, cssVars: null };
  }
  if (item.gh) {
    try {
      const repoParts = item.gh.split('/');
      const repo = repoParts.slice(0, 3).join('/');
      const entryPath = repoParts.slice(3).join('/');
      const g = await followGh({ repo, entryPath, stop: (s) => projectProvides(prof, s) });
      if (g.unresolved.length) throw new Error('UNRESOLVED_IMPORTS ' + g.unresolved.join(', '));
      return {
        origin: 'gh', sourceUrl: `https://github.com/${repo.split('/').slice(0, 2).join('/')}/blob/${repoParts[2]}/${entryPath}`,
        entry: g.entry, files: [...g.files].map(([p, content]) => ({ path: p, content })), deps: [...new Set([...realPackages(item.deps), ...realPackages(g.deps)])],
        external: g.external, css: null, cssVars: null,
      };
    } catch (e) { errors.push('gh: ' + e.message); }
  }
  for (const url of [item.json, item.mirror].filter(Boolean)) {
    try {
      const doc = await fetchJsonItem(url);
      return await jsonBundle(prof, item, doc, url);
    } catch (e) { errors.push(url + ': ' + e.message); }
  }
  if (item.ghFiles?.length) {
    try {
      const repo = item.ghFiles[0].split('/').slice(0, 3).join('/');
      const files = [];
      for (const f of item.ghFiles) files.push({ path: f.split('/').slice(3).join('/'), content: rawSource(await getText(`https://raw.githubusercontent.com/${f}`)) });
      return await jsonBundle(prof, item, { files, dependencies: item.deps, registryDependencies: item.rdeps }, `https://github.com/${repo}`);
    } catch (e) { errors.push('ghFiles: ' + e.message); }
  }
  const err = new Error('FETCH_FAILED ' + item.id + ' — ' + errors.join(' | '));
  err.code = 'FETCH_FAILED';
  throw err;
}

/**
 * A registry's source read raw from its repo, as its published JSON would give it: shadcn's own sources import
 * `cn` from a workspace alias `"cn"` that its registry build rewrites to `@/lib/utils` — read as a package, it
 * would install an unrelated npm package named `cn`.
 */
export function rawSource(content) {
  return content.replace(/(\bfrom\s+)(["'])cn\2/g, '$1$2@/lib/utils$2');
}

/**
 * A registry's dependency list as npm packages: shadcn DECLARES its workspace alias `cn` there (89 catalog items list it),
 * and installing it would add an unrelated npm package named `cn` to the owner's package.json (Discard then leaves it behind).
 */
export const realPackages = (list) => (list || []).filter((d) => d && d !== 'cn');

/** shadcn-schema JSON -> bundle; unresolved `@/registry|components/ui/x` become shadcn/registry deps. */
async function jsonBundle(prof, item, doc, url) {
  // a registry's workspace alias `from "cn"` is the project's utils, in every file it serves (JSON items too, not only raw repo files)
  const files = (doc.files || []).filter((f) => f.content).map((f) => ({ path: f.path, content: rawSource(f.content) }));
  const deps = new Set(realPackages(doc.dependencies));
  const external = {};
  const have = new Set(files.map((f) => f.path));
  const extra = [];
  const queued = new Set();
  const scan = (f) => {
    for (const imp of importsOf(f.path, f.content)) {
      const s = imp.spec;
      const prov = projectProvides(prof, s);
      if (prov) { external[s] = prov; continue; }
      if (s.startsWith('@/') || s.startsWith('~/')) {
        const local = files.find((x) => x.path.replace(/\.(tsx|ts|jsx|js)$/, '').endsWith(s.replace(/^[@~]\/(registry\/[^/]+\/)?/, '')));
        if (local) continue;
        if (/lib\/utils$/.test(s) || queued.has(s)) continue;           // local utils copy is added at write time
        queued.add(s);
        const ui = /(?:^|\/)ui\/([a-z0-9-]+)$/.exec(s);
        extra.push({ spec: s, name: ui ? ui[1] : s.split('/').pop() });
      } else if (!s.startsWith('.') && !imp.typeOnly) {
        const n = pkgName(s);
        if (!BUILTIN.has(n)) deps.add(n);
      }
    }
  };
  for (const f of files) scan(f);
  // registry-internal deps the item did not embed: shadcn primitives by the project's style — and theirs in turn
  // (a login block's `field` imports `separator` and `label`)
  for (let i = 0; i < extra.length; i++) {
    const x = extra[i];
    const style = prof.base === 'base-ui' ? 'base-nova' : 'new-york-v4';
    let got = null;
    // a file of another block of the same registry (`@/registry/blocks/radix/navbar-04/components/logo`): that
    // block's own JSON, beside this one, holds it
    const sib = /registry\/blocks\/(?:[^/]+\/)?([a-z0-9-]+)\/(.+)$/.exec(x.spec);
    if (sib) {
      try {
        const doc2 = await fetchJsonItem(url.replace(/[^/]+\.json$/, sib[1] + '.json'));
        const f = (doc2.files || []).find((y) => y.content && y.path.replace(/\.(tsx|ts|jsx|js)$/, '').endsWith(sib[1] + '/' + sib[2]));
        if (f) got = { files: [{ path: f.path, content: f.content }], dependencies: doc2.dependencies || [] };
      } catch { /* unresolved */ }
    } else {
      try { got = await fetchJsonItem(`https://ui.shadcn.com/r/styles/${style}/${x.name}.json`); } catch { /* next */ }
      if (!got) {
        try {
          const content = rawSource(await getText(`https://raw.githubusercontent.com/shadcn-ui/ui/main/apps/v4/registry/${style}/ui/${x.name}.tsx`));
          got = { files: [{ path: `registry/${style}/ui/${x.name}.tsx`, content }], dependencies: [] };
        } catch { /* next */ }
      }
      // not a shadcn primitive (a registry's own `ui/marquee`): the registry's item of that name, beside this one
      if (!got && /\/[^/]+\.json$/.test(url)) {
        try {
          const own = await fetchJsonItem(url.replace(/[^/]+\.json$/, x.name + '.json'));
          got = { files: own.files.filter((f) => f.content), dependencies: own.dependencies || [] };
        } catch { /* unresolved */ }
      }
    }
    if (!got) throw new Error('UNRESOLVED_REGISTRY_DEP ' + x.spec);
    for (const d of realPackages(got.dependencies)) deps.add(d);
    for (const f of got.files) if (!have.has(f.path)) {
      const nf = { path: f.path, content: rawSource(f.content), aliasOf: x.spec };
      files.push(nf);
      have.add(f.path);
      scan(nf);
    }
  }
  let mainIdx = Math.max(0, files.findIndex((f) => /\.(tsx|jsx)$/.test(f.path) && !/\/ui\//.test(f.path)));
  // a block's `app/login/page.tsx` only centres its `<LoginForm/>`: the section is the one component it shows
  const page = files[mainIdx];
  if (/(^|\/)page\.(tsx|jsx)$/.test(page.path)) {
    const shown = importsOf(page.path, page.content).filter((i) => !i.typeOnly).map((i) => i.spec.replace(/^[@~]\//, '').replace(/^(\.\.?\/)+/, '').replace(/^registry\/[^/]+\//, ''))
      .map((body) => files.findIndex((f) => f !== page && /\.(tsx|jsx)$/.test(f.path) && !/\/ui\//.test(f.path) && f.path.replace(/\.(tsx|jsx)$/, '').endsWith(body)))
      .filter((i) => i >= 0);
    if (shown.length === 1) mainIdx = shown[0];
  }
  const entry = files[mainIdx].path;
  return { origin: 'json', sourceUrl: url, entry, files, deps: [...deps], external, css: doc.css || null, cssVars: doc.cssVars || null };
}

/**
 * The project's `radix-ui` umbrella (shadcn v4 bases): every `@radix-ui/react-<x>` is also `radix-ui/<x>`, resolvable
 * from the project even under pnpm's strict layout. A design's `@radix-ui/react-toggle` is rewritten to
 * `radix-ui/toggle` instead of installing a package the running dev server may not see until it restarts
 * ("Module not found: Can't resolve '@radix-ui/react-toggle'" broke an owner's page). Returns the part names, or null.
 */
export function radixUmbrella(prof) {
  if (!prof.deps || !Object.prototype.hasOwnProperty.call(prof.deps, 'radix-ui')) return null;
  try {
    const names = fs.readdirSync(path.join(prof.root, 'node_modules', 'radix-ui', 'dist'))
      .filter((f) => f.endsWith('.mjs')).map((f) => f.slice(0, -4)).filter((n) => n !== 'index' && n !== 'internal');
    return names.length ? new Set(names) : null;
  } catch { return null; }
}

/**
 * Write a bundle into <componentsDir>/dh-tryon/<slug>/. Returns the stage record.
 */
export function writeBundle(prof, item, bundle, { baseDir, dirName } = {}) {
  const slug = slugOf(item);
  const relDir = path.posix.join(baseDir || path.posix.join(prof.componentsDir, 'dh-tryon'), dirName || slug);
  const absDir = path.join(prof.root, relDir);
  fs.rmSync(absDir, { recursive: true, force: true });
  fs.mkdirSync(absDir, { recursive: true });

  // placement: entry -> <slug>.<ext>; others -> basename, de-duplicated with their parent dir name
  const placed = new Map();
  const used = new Set();
  const ext = (p) => (/\.(tsx|ts|jsx|js|css)$/.exec(p) || ['', 'tsx'])[1];
  const entryName = slug + '.' + ext(bundle.entry);
  placed.set(bundle.entry, entryName);
  used.add(entryName);
  for (const f of bundle.files) {
    if (placed.has(f.path)) continue;
    let base = path.posix.basename(f.path);
    if (used.has(base)) base = path.posix.basename(path.posix.dirname(f.path)) + '-' + base;
    while (used.has(base)) base = '_' + base;
    used.add(base);
    placed.set(f.path, base);
  }
  const needUtils = bundle.files.some((f) => importsOf(f.path, f.content).some((i) => /lib\/utils$/.test(i.spec) && !bundle.external[i.spec]));
  if (needUtils) { placed.set('__utils__', 'utils.ts'); used.add('utils.ts'); }

  const resolveTarget = (fromPath, spec) => {
    if (bundle.external[spec]) return bundle.external[spec];
    if (/lib\/utils$/.test(spec) && needUtils) return './utils';
    const cands = [];
    if (spec.startsWith('.')) cands.push(path.posix.normalize(path.posix.join(path.posix.dirname(fromPath), spec)));
    const body = spec.replace(/^[@~]\//, '');
    for (const f of bundle.files) {
      const noext = f.path.replace(/\.(tsx|ts|jsx|js)$/, '').replace(/\/index$/, '');
      if (cands.includes(noext) || cands.includes(f.path) || noext.endsWith('/' + body) || noext === body
        || (f.aliasOf && f.aliasOf === spec)) {
        return './' + placed.get(f.path).replace(/\.(tsx|ts|jsx|js)$/, '');
      }
      // registry-scoped aliases: @/registry/<style>/ui/x ↔ registry/<style>/ui/x
      if (spec.startsWith('@/registry/') && noext === spec.slice(2)) return './' + placed.get(f.path).replace(/\.(tsx|ts|jsx|js)$/, '');
    }
    const ui = /(?:^|\/)ui\/([a-z0-9-]+)$/.exec(spec);
    if (ui) {
      const f = bundle.files.find((x) => x.path.replace(/\.(tsx|ts|jsx|js)$/, '').endsWith('/ui/' + ui[1]));
      if (f) return './' + placed.get(f.path).replace(/\.(tsx|ts|jsx|js)$/, '');
    }
    return null;
  };

  const header = item.ai
    ? (p) => `/* AI-generated — ${item.t} · written by this project's AI agent for the owner (deckhand try-on draft ${item.n}); not a third-party design, no licence notice applies; review the wording before launch${p !== bundle.entry ? ' · ' + path.posix.basename(p) : ''} · staged by deckhand try-on */\n`
    : (p) => `/* ${item.t || item.n} — ${item.r}/${item.n} (${item.lic || 'MIT'}) · source: ${bundle.sourceUrl}${p !== bundle.entry ? ' · ' + p : ''} · staged by deckhand try-on */\n`;
  const written = [];
  const problems = [];
  const umbrella = radixUmbrella(prof);
  const viaUmbrella = new Set();
  const shims = new Set();
  for (const f of bundle.files) {
    let code = f.content;
    const imps = importsOf(f.path, code).sort((a, b) => b.start - a.start);
    for (const imp of imps) {
      const s = imp.spec;
      if (prof.framework !== 'next' && NEXT_SHIMS[s]) {
        const q = code[imp.start];
        code = code.slice(0, imp.start) + q + './' + NEXT_SHIMS[s][0].replace(/\.tsx$/, '') + q + code.slice(imp.end);
        shims.add(s);
        continue;
      }
      const rx = /^@radix-ui\/react-([a-z0-9-]+)$/.exec(s);
      if (rx && umbrella && umbrella.has(rx[1]) && !depInstalled(prof, s)) {
        const q = code[imp.start];
        code = code.slice(0, imp.start) + q + 'radix-ui/' + rx[1] + q + code.slice(imp.end);
        viaUmbrella.add(s);
        continue;
      }
      if (!(s.startsWith('.') || s.startsWith('@/') || s.startsWith('~/'))) continue;
      const t = resolveTarget(f.path, s);
      if (!t) { problems.push(`${f.path}: cannot resolve ${s}`); continue; }
      const q = code[imp.start];
      code = code.slice(0, imp.start) + q + t + q + code.slice(imp.end);
    }
    if (/\.(tsx|jsx)$/.test(f.path)) code = reactAttrs(f.path, normalizeClasses(f.path, code).code);
    if (/\.(tsx|ts)$/.test(f.path)) code = compatFixes(f.path, code);
    if (/\.(tsx|jsx)$/.test(f.path)) code = fitProjectPrimitives(prof, f.path, code);
    if (prof.rsc && /\.(tsx|jsx|ts|js)$/.test(f.path) && needsClient(code)) code = `"use client"\n\n` + code;
    const out = header(f.path) + code;
    const abs = path.join(absDir, placed.get(f.path));
    fs.writeFileSync(abs, out);
    written.push(path.posix.join(relDir, placed.get(f.path)));
  }
  if (needUtils) {
    fs.writeFileSync(path.join(absDir, 'utils.ts'), UTILS_SRC);
    written.push(path.posix.join(relDir, 'utils.ts'));
  }
  for (const sp of shims) {
    const [name, src] = NEXT_SHIMS[sp];
    fs.writeFileSync(path.join(absDir, name), src);
    written.push(path.posix.join(relDir, name));
  }
  const deps = new Set([...bundle.deps].filter((d) => !viaUmbrella.has(d)));
  if (needUtils) { deps.add('clsx'); deps.add('tailwind-merge'); }
  const allDeps = [...deps].filter((d) => !BUILTIN.has(d));
  const missingDeps = allDeps.filter((d) => !depInstalled(prof, d));

  // brand-logo components a design ships as demo social proof (registry svgs/ folders, known marks)
  const BRANDS = /^(vercel|spotify|supabase|hulu|bolt|beacon|firebase|claude|claude-ai|openai|gemini|google|google-palm|slack|figma|linear|twilio|clerk|github|stripe|nvidia|netflix|cisco|lemon-squeezy|laravel|lilly|nike|column|replit|magic-ui|vs-codium|media-wiki|trustpilot|g2|tailwind|nextjs|zapier|notion|airbnb|microsoft|apple|amazon|meta|paypal|shopify)(-\w+)?\.tsx$/;
  const logoFiles = [...placed].filter(([repo, base]) => repo !== bundle.entry && (/\/svgs?\//.test(repo) || /\/logos?\//.test(repo) || BRANDS.test(base))).map(([, base]) => base);
  const entryRel = path.posix.join(relDir, entryName);
  const entryCode = fs.readFileSync(path.join(prof.root, entryRel), 'utf8');
  const exp = entryExport(entryRel, entryCode);
  return {
    slug, relDir, entry: entryRel, spec: specFor(prof, entryRel) || './' + entryRel, export: exp,
    files: written, deps: allDeps, missingDeps, problems, sourceUrl: bundle.sourceUrl, viaUmbrella: [...viaUmbrella],
    css: bundle.css, cssVars: bundle.cssVars, logoFiles,
  };
}
