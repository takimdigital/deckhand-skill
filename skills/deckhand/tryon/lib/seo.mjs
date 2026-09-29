/**
 * seo.mjs — make a site findable, in its own code, deterministically (no model call).
 *
 *   seoInspect(root)        what the source already has: robots / sitemap / manifest / icons / OG image /
 *                           not-found / llms.txt, the root layout's metadata (keys, title kind, an inherited
 *                           canonical), <html lang>, JSON-LD, and per page: route, client component or not,
 *                           metadata / generateMetadata, title, description, canonical, <h1> count.
 *   seoApply(root, plan)    ADD what is missing and IMPROVE what is weak — never overwrite the owner's words:
 *                           a string title becomes { default: <same>, template: "%s — Brand" }; missing keys
 *                           are added; a canonical in the ROOT layout (which every page would inherit) is moved
 *                           to the pages. Files it owns carry a `dh:seo` marker and are regenerated; files the
 *                           owner wrote are never replaced. Every write is journaled: seoUndo() is byte-exact.
 *   plan (from `dh seo apply`, built from the brief's confirmed facts — nothing is invented here):
 *     { site: { name, url, description, tagline, locale, languages[], themeColor, background, twitter },
 *       jsonld: {…graph…}, pages: [{ route, title?, description?, noindex? }], robots: { ai, disallow[],
 *       training[] }, llms: "markdown", indexnow: "key" | null, verification: { google?, bing? } }
 * Next.js App Router: full support. Next.js Pages Router, Vite and static sites: index.html head tags plus
 * static robots.txt / sitemap.xml / llms.txt.
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { detectProject, specFor } from './project.mjs';

const require = createRequire(import.meta.url);
const { parse, walk, jsxName, attr } = require('./ast.cjs');

const MARK = 'dh:seo';
const HEADER = `// ${MARK} — written by deckhand (\`dh seo apply\`) from .deckhand/brief.json. Edit the brief and re-run; \`dh seo undo\` restores the previous files.\n`;
const J = (v) => JSON.stringify(v);
const exists = (p) => fs.existsSync(p);
const read = (p) => fs.readFileSync(p, 'utf8');
const rel = (root, p) => path.relative(root, p).split(path.sep).join('/');
const ours = (text) => text.includes(MARK);

function firstExisting(root, dir, base, exts) {
  for (const e of exts) {
    const p = path.join(root, dir, base + e);
    if (exists(p)) return rel(root, p);
  }
  return null;
}

/** app/(marketing)/about/page.tsx -> { route: "/about", dynamic: false } */
function routeOf(appDir, file) {
  const parts = path.posix.dirname(file.slice(appDir.length + 1)).split('/').filter((s) => s && s !== '.');
  const segs = parts.filter((s) => !/^\(.*\)$/.test(s) && !s.startsWith('@'));
  return { route: '/' + segs.join('/'), dynamic: segs.some((s) => s.startsWith('[')) };
}

function walkFiles(dir, out = [], skip = new Set(['node_modules', '.next', '.git', 'dist', 'build'])) {
  if (!exists(dir)) return out;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (skip.has(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walkFiles(p, out, skip);
    else out.push(p);
  }
  return out;
}

function unwrap(n) {
  while (n && (n.type === 'TSSatisfiesExpression' || n.type === 'TSAsExpression' || n.type === 'ParenthesizedExpression')) n = n.expression;
  return n;
}
const keyName = (p) => p && p.key && (p.key.name || p.key.value);
const propOf = (obj, name) => (obj && obj.type === 'ObjectExpression' ? obj.properties.find((p) => p.type === 'ObjectProperty' && keyName(p) === name) : null);
const litStr = (n) => (n && n.type === 'StringLiteral' ? n.value : n && n.type === 'TemplateLiteral' && !n.expressions.length ? n.quasis[0].value.cooked : null);

/** The `export const metadata` object (and its declarator), `generateMetadata`, and 'use client' of a module. */
function moduleMeta(code, file) {
  const ast = parse(file, code);
  let meta = null, gen = false;
  const client = ast.program.directives?.some((d) => d.value.value === 'use client') || /^\s*['"]use client['"]/.test(code);
  for (const st of ast.program.body) {
    if (st.type !== 'ExportNamedDeclaration' || !st.declaration) continue;
    const d = st.declaration;
    if (d.type === 'FunctionDeclaration' && d.id?.name === 'generateMetadata') gen = true;
    if (d.type === 'VariableDeclaration') {
      for (const v of d.declarations) {
        if (v.id?.name === 'metadata') meta = { decl: v, obj: unwrap(v.init) };
        if (v.id?.name === 'generateMetadata') gen = true;
      }
    }
  }
  return { ast, meta, gen, client };
}

function describeMeta(meta) {
  if (!meta || !meta.obj || meta.obj.type !== 'ObjectExpression') return null;
  const o = meta.obj;
  const title = propOf(o, 'title');
  const t = title ? unwrap(title.value) : null;
  const alt = propOf(o, 'alternates');
  return {
    keys: o.properties.map(keyName).filter(Boolean),
    titleKind: !t ? 'none' : t.type === 'ObjectExpression' ? (propOf(t, 'template') ? 'template' : 'object') : 'string',
    title: t ? (litStr(t) ?? litStr(propOf(t, 'default')?.value) ?? litStr(propOf(t, 'absolute')?.value)) : null,
    description: litStr(propOf(o, 'description')?.value) ?? (propOf(o, 'description') ? '(expression)' : null),
    canonical: !!(alt && propOf(unwrap(alt.value), 'canonical')),
  };
}

function countJsx(ast, name) {
  let n = 0;
  walk(ast, (node) => { if (node.type === 'JSXOpeningElement' && jsxName(node.name) === name) n++; return true; });
  return n;
}

export function seoInspect(rootIn) {
  const prof = detectProject(rootIn);
  const root = prof.root;
  const out = { framework: prof.framework, router: null, appDir: prof.appDir, lang: prof.lang, files: {}, layout: null, pages: [], jsonLd: false, notes: [] };
  const pub = (f) => exists(path.join(root, 'public', f));
  out.files.llms = pub('llms.txt');
  out.files.indexnow = fs.existsSync(path.join(root, 'public')) && fs.readdirSync(path.join(root, 'public')).some((f) => /^[a-f0-9]{32,128}\.txt$/.test(f));
  const jsonLdIn = (dir) => walkFiles(path.join(root, dir)).some((p) => /\.(tsx|jsx|ts|js|html)$/.test(p) && read(p).includes('application/ld+json'));

  if (prof.framework === 'next' && prof.appDir) {
    out.router = 'app';
    const A = prof.appDir;
    const f = (base, exts) => firstExisting(root, A, base, exts);
    Object.assign(out.files, {
      robots: f('robots', ['.ts', '.js', '.txt']) || (pub('robots.txt') ? 'public/robots.txt' : null),
      sitemap: f('sitemap', ['.ts', '.js', '.xml']) || (pub('sitemap.xml') ? 'public/sitemap.xml' : null),
      manifest: f('manifest', ['.ts', '.js', '.json', '.webmanifest']),
      icon: f('icon', ['.svg', '.png', '.ico', '.jpg', '.tsx', '.ts']) || f('favicon', ['.ico']),
      appleIcon: f('apple-icon', ['.png', '.jpg', '.tsx', '.ts']),
      ogImage: f('opengraph-image', ['.tsx', '.ts', '.jsx', '.js', '.png', '.jpg']),
      notFound: f('not-found', ['.tsx', '.jsx', '.ts', '.js']),
    });
    const layout = f('layout', ['.tsx', '.jsx', '.ts', '.js']);
    if (layout) {
      const code = read(path.join(root, layout));
      const m = moduleMeta(code, layout);
      let lang = null, hasBody = false;
      walk(m.ast, (n) => {
        if (n.type === 'JSXOpeningElement' && jsxName(n.name) === 'html') {
          const a = attr(n, 'lang');
          lang = a ? (a.value?.type === 'StringLiteral' ? a.value.value : '(expression)') : null;
        }
        if (n.type === 'JSXOpeningElement' && jsxName(n.name) === 'body') hasBody = true;
        return true;
      });
      out.layout = { file: layout, metadata: describeMeta(m.meta), generateMetadata: m.gen, lang, hasBody };
    }
    for (const p of walkFiles(path.join(root, A))) {
      const r = rel(root, p);
      if (!/\/page\.(tsx|jsx|ts|js|mdx)$/.test(r)) continue;
      const { route, dynamic } = routeOf(A, r);
      let info = { file: r, route, dynamic, client: false, metadata: null, generateMetadata: false, h1: 0 };
      try {
        const code = read(p);
        const m = moduleMeta(code, r);
        info = { ...info, client: m.client, metadata: describeMeta(m.meta), generateMetadata: m.gen, h1: countJsx(m.ast, 'h1') };
      } catch (e) {
        info.error = String(e.message).split('\n')[0];
      }
      out.pages.push(info);
    }
    out.pages.sort((a, b) => a.route.localeCompare(b.route));
    out.jsonLd = jsonLdIn(A) || jsonLdIn(prof.componentsDir);
    out.i18nSegment = fs.readdirSync(path.join(root, A), { withFileTypes: true }).find((d) => d.isDirectory() && /^\[(locale|lang|lng)\]$/.test(d.name))?.name || null;
  } else if (prof.framework === 'next') {
    out.router = 'pages';
    out.files.robots = pub('robots.txt') ? 'public/robots.txt' : null;
    out.files.sitemap = pub('sitemap.xml') ? 'public/sitemap.xml' : null;
    out.notes.push('Pages Router: per-page <Head> tags are not written automatically — add title/description/canonical in each page with next/head');
  } else {
    const index = ['index.html', 'public/index.html'].find((x) => exists(path.join(root, x)));
    out.router = index ? 'static' : null;
    out.files.robots = pub('robots.txt') ? 'public/robots.txt' : null;
    out.files.sitemap = pub('sitemap.xml') ? 'public/sitemap.xml' : null;
    if (index) {
      const h = read(path.join(root, index));
      out.index = { file: index, title: (/<title>([^<]*)<\/title>/i.exec(h) || [])[1] || null, description: /<meta\s+name=["']description["']/i.test(h),
        canonical: /rel=["']canonical["']/i.test(h), og: /property=["']og:/i.test(h), lang: (/<html[^>]*\blang=["']([^"']+)/i.exec(h) || [])[1] || null,
        jsonLd: h.includes('application/ld+json'), spa: /<div id=["'](root|app)["']>\s*<\/div>/i.test(h) };
      out.jsonLd = out.index.jsonLd;
    }
  }
  return out;
}

/* ------------------------------------------------------------------ apply */

const shaOf = (abs) => (exists(abs) ? crypto.createHash('sha256').update(fs.readFileSync(abs)).digest('hex') : null);

function journal(root) {
  const files = {};
  return {
    write(relPath, text) {
      const abs = path.join(root, relPath);
      if (!(relPath in files)) files[relPath] = exists(abs) ? read(abs) : null;
      if (exists(abs) && read(abs) === text) return false;
      fs.mkdirSync(path.dirname(abs), { recursive: true });
      fs.writeFileSync(abs, text);
      return true;
    },
    save() {
      const changed = Object.entries(files).filter(([p, before]) => (exists(path.join(root, p)) ? read(path.join(root, p)) : null) !== before);
      if (!changed.length) return [];
      const d = path.join(root, '.deckhand', 'tryon', 'seo');
      fs.mkdirSync(d, { recursive: true });
      fs.writeFileSync(path.join(d, 'last.json'), JSON.stringify({ at: new Date().toISOString(), files: Object.fromEntries(changed),
        after: Object.fromEntries(changed.map(([p]) => [p, shaOf(path.join(root, p))])) }));
      return changed.map(([p]) => p);
    },
  };
}

const ts = (prof) => prof.lang === 'ts';

function siteModule(prof, plan) {
  const T = ts(prof);
  const s = plan.site;
  const pages = plan.pages.filter((p) => !p.noindex).map((p) => ({ route: p.route }));
  return HEADER + `
export const SITE = {
  name: ${J(s.name)},
  description: ${J(s.description || '')},
  tagline: ${J(s.tagline || '')},
  url: (process.env.NEXT_PUBLIC_SITE_URL || ${J(s.url)}).replace(/\\/$/, ""),
  locale: ${J(s.locale || 'en_US')},
  languages: ${J(s.languages || ['en'])},
  themeColor: ${J(s.themeColor || '#111111')},
  background: ${J(s.background || '#ffffff')},
}${T ? ' as const' : ''};

/** A preview/staging deployment sets DH_NOINDEX=1: nothing on it is indexed. The real domain never sets it. */
export const NOINDEX = process.env.DH_NOINDEX === "1";

/** Public, indexable routes (from the plan). The sitemap is built from this list. */
export const PAGES${T ? ': { route: string }[]' : ''} = ${J(pages)};

/** Who the business is, for search engines and AI answers — only facts the owner confirmed. */
export const JSON_LD = ${JSON.stringify(plan.jsonld, null, 2)};
`;
}

function robotsModule(prof, plan, siteSpec) {
  const T = ts(prof);
  const r = plan.robots || {};
  const disallow = [...new Set(['/api/', ...(r.disallow || [])])];
  const training = r.ai === 'search-only' ? (r.training || []) : [];
  return HEADER + (T ? 'import type { MetadataRoute } from "next";\n' : '') + `import { SITE, NOINDEX } from ${J(siteSpec)};

export default function robots()${T ? ': MetadataRoute.Robots' : ''} {
  // a preview stays crawlable so search engines SEE its noindex (a robots block would hide the noindex)
  if (NOINDEX) return { rules: [{ userAgent: "*", allow: "/" }] };
  return {
    rules: [
      { userAgent: "*", allow: "/", disallow: ${J(disallow)} },${training.length ? `
      // the owner chose "search-only": AI answer engines may read the site, model-training crawlers may not
      { userAgent: ${J(training)}, disallow: "/" },` : ''}
    ],
    sitemap: \`\${SITE.url}/sitemap.xml\`,
    host: SITE.url,
  };
}
`;
}

function sitemapModule(prof, plan, siteSpec, i18n) {
  const T = ts(prof);
  const langs = plan.site.languages || ['en'];
  const multi = i18n && langs.length > 1;
  return HEADER + (T ? 'import type { MetadataRoute } from "next";\n' : '') + `import { SITE, PAGES, NOINDEX } from ${J(siteSpec)};

export default function sitemap()${T ? ': MetadataRoute.Sitemap' : ''} {
  if (NOINDEX) return [];
${multi ? `  const langs = ${J(langs)};
  // every page in every language, each listing all its translations (+ x-default) — reciprocal hreflang
  return PAGES.flatMap((p) => langs.map((l) => ({
    url: \`\${SITE.url}/\${l}\${p.route === "/" ? "/" : p.route}\`,
    alternates: { languages: Object.fromEntries([...langs.map((x) => [x, \`\${SITE.url}/\${x}\${p.route === "/" ? "" : p.route}\`]), ["x-default", \`\${SITE.url}/\${langs[0]}\${p.route === "/" ? "" : p.route}\`]]) },
  })));` : `  return PAGES.map((p) => ({ url: SITE.url + p.route }));`}
}
`;
}

function manifestModule(prof, siteSpec) {
  const T = ts(prof);
  return HEADER + (T ? 'import type { MetadataRoute } from "next";\n' : '') + `import { SITE } from ${J(siteSpec)};

export default function manifest()${T ? ': MetadataRoute.Manifest' : ''} {
  return {
    name: SITE.name,
    short_name: SITE.name.length > 12 ? SITE.name.split(/\\s+/)[0].slice(0, 12) : SITE.name,
    description: SITE.description,
    start_url: "/",
    display: "standalone",
    background_color: SITE.background,
    theme_color: SITE.themeColor,
  };
}
`;
}

function ogModule(prof, siteSpec) {
  return HEADER + `import { ImageResponse } from "next/og";
import { SITE } from ${J(siteSpec)};

export const alt = SITE.name;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/** The card shown when a page is shared (WhatsApp, Facebook, LinkedIn, X, iMessage): the brand, never a stock photo. */
export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", width: "100%", height: "100%", padding: 88, background: SITE.themeColor, color: "#ffffff" }}>
        <div style={{ fontSize: 76, fontWeight: 700, lineHeight: 1.1 }}>{SITE.name}</div>
        {SITE.tagline ? <div style={{ fontSize: 38, marginTop: 28, opacity: 0.9 }}>{SITE.tagline}</div> : null}
      </div>
    ),
    size,
  );
}
`;
}

function jsonLdComponent(prof) {
  const T = ts(prof);
  return HEADER + `/** Structured data for search engines and AI answers. \`<\` is escaped so no string can close the script tag. */
export function JsonLd({ data }${T ? ': { data: unknown }' : ''}) {
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, "\\\\u003c") }} />;
}
`;
}

function notFoundModule(prof) {
  const T = ts(prof);
  return HEADER + (T ? 'import type { Metadata } from "next";\n' : '') + `import Link from "next/link";

export const metadata${T ? ': Metadata' : ''} = { title: "Page not found", robots: { index: false } };

/** Unknown URLs answer a real 404 (never a soft 404, never a redirect to the home page). */
export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-[60vh] max-w-xl flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="text-3xl font-semibold">Page not found</h1>
      <p className="text-muted-foreground">This page does not exist or has moved.</p>
      <Link href="/" className="underline underline-offset-4">Back to the home page</Link>
    </main>
  );
}
`;
}

/** Text of a property to add inside an object literal. */
const prop = (k, v) => `${/^[A-Za-z_$][\w$]*$/.test(k) ? k : J(k)}: ${v}`;

const lineIndent = (code, pos) => /^[ \t]*/.exec(code.slice(code.lastIndexOf('\n', pos - 1) + 1))[0];

/** Indentation for a property of `obj`: its first property's own line, else the object's line + 2 spaces. */
function propIndent(code, obj) {
  const first = obj.properties[0];
  if (first && code.slice(obj.start, first.start).includes('\n')) return lineIndent(code, first.start);
  return lineIndent(code, obj.start) + '  ';
}

/** Add properties at the end of an object literal, keeping its comma style. */
function insertProps(code, obj, props) {
  const ind = propIndent(code, obj);
  if (!obj.properties.length) {
    return { start: obj.start + 1, end: obj.end - 1, text: props.map((p) => `\n${ind}${p},`).join('') + '\n' + lineIndent(code, obj.start) };
  }
  const last = obj.properties[obj.properties.length - 1];
  const comma = /^\s*,/.exec(code.slice(last.end, obj.end - 1));
  const at = comma ? last.end + comma[0].length : last.end;
  return { start: at, end: at, text: (comma ? '' : ',') + props.map((p) => `\n${ind}${p}`).join(',') + (comma ? ',' : '') };
}

/** Remove one property (and its comma, and its line when it stands alone). */
function removeProp(code, p) {
  let start = p.start, end = p.end;
  const comma = /^\s*,/.exec(code.slice(end));
  if (comma) end += comma[0].length;
  const ls = code.lastIndexOf('\n', start - 1);
  if (!code.slice(ls + 1, start).trim()) start = ls;
  return { start, end, text: '' };
}

function applyEdits(code, edits) {
  let out = code;
  for (const e of [...edits].sort((a, b) => b.start - a.start)) out = out.slice(0, e.start) + e.text + out.slice(e.end);
  return out;
}

function addImports(code, file, lines) {
  const ast = parse(file, code);
  const have = (l) => code.includes(l);
  const todo = lines.filter((l) => !have(l));
  if (!todo.length) return code;
  const imports = ast.program.body.filter((s) => s.type === 'ImportDeclaration');
  const at = imports.length ? imports[imports.length - 1].end : (ast.program.directives?.length ? ast.program.directives[ast.program.directives.length - 1].end : 0);
  return code.slice(0, at) + (at ? '\n' : '') + todo.join('\n') + (at ? '' : '\n\n') + code.slice(at).replace(at ? /^/ : /^\n+/, '');
}

/** Import exactly the names the module uses from `source` (merging into an existing import). */
function ensureNamedImport(code, file, source, names, always = false, typeOnly = false) {
  const ast = parse(file, code);
  const used = always ? names : names.filter((n) => {
    let hit = false;
    walk(ast, (node, parent) => {
      const declOrKey = !!parent && (parent.type === 'ImportSpecifier'
        || (parent.type === 'ObjectProperty' && parent.key === node && !parent.computed)
        || (parent.type === 'MemberExpression' && parent.property === node && !parent.computed));
      if (node.type === 'Identifier' && node.name === n && !declOrKey) hit = true;
      return !hit;
    });
    return hit;
  });
  if (!used.length) return code;
  const imp = ast.program.body.find((s) => s.type === 'ImportDeclaration' && s.source.value === source && s.specifiers.every((x) => x.type === 'ImportSpecifier'));
  if (imp) {
    const have = imp.specifiers.map((x) => x.local.name);
    const missing = used.filter((n) => !have.includes(n));
    if (!missing.length) return code;
    const last = imp.specifiers[imp.specifiers.length - 1];
    return code.slice(0, last.end) + ', ' + missing.join(', ') + code.slice(last.end);
  }
  if (typeOnly && ast.program.body.some((s) => s.type === 'ImportDeclaration' && s.source.value === source && s.specifiers.some((x) => x.local.name === names[0]))) return code;
  return addImports(code, file, [`import ${typeOnly ? 'type ' : ''}{ ${used.join(', ')} } from ${J(source)};`]);
}

/** The title a page should declare: absolute when it already carries the brand (the template would repeat it). */
function titleExpr(title, brand) {
  return title.toLowerCase().includes(String(brand).toLowerCase()) ? `{ absolute: ${J(title)} }` : J(title);
}

function improveLayout(prof, plan, code, file, siteSpec, jsonLdSpec, changes, multiPage) {
  const T = ts(prof);
  const brand = plan.site.name;
  let m = moduleMeta(code, file);
  if (m.gen) {
    changes.push({ file, skipped: 'the layout uses generateMetadata — add metadataBase, title template, description, openGraph, twitter and robots there by hand' });
  } else if (!m.meta) {
    const lines = [
      `export const metadata${T ? ': Metadata' : ''} = {`,
      '  metadataBase: new URL(SITE.url),',
      '  title: { default: SITE.name, template: `%s — ${SITE.name}` },',
      '  description: SITE.description,',
      '  applicationName: SITE.name,',
      '  openGraph: { type: "website", siteName: SITE.name, locale: SITE.locale },',
      '  twitter: { card: "summary_large_image" },',
      '  robots: NOINDEX ? { index: false, follow: false } : { index: true, follow: true },',
      ...(plan.verification?.google || plan.verification?.bing ? [`  verification: { ${[plan.verification.google ? `google: ${J(plan.verification.google)}` : '', plan.verification.bing ? `other: { "msvalidate.01": ${J(plan.verification.bing)} }` : ''].filter(Boolean).join(', ')} },`] : []),
      '};',
    ];
    const ast = parse(file, code);
    const imports = ast.program.body.filter((s) => s.type === 'ImportDeclaration');
    const at = imports.length ? imports[imports.length - 1].end : 0;
    code = code.slice(0, at) + '\n\n' + lines.join('\n') + code.slice(at);
    changes.push({ file, added: 'metadata (metadataBase, title template, description, openGraph, twitter, robots)' });
  } else if (m.meta.obj?.type === 'ObjectExpression') {
    const o = m.meta.obj;
    const edits = [], add = [], what = [];
    const title = propOf(o, 'title');
    if (!propOf(o, 'metadataBase')) { add.push(prop('metadataBase', 'new URL(SITE.url)')); what.push('metadataBase'); }
    if (!title) { add.push(prop('title', '{ default: SITE.name, template: `%s — ${SITE.name}` }')); what.push('title template'); }
    else {
      const t = unwrap(title.value);
      const s = litStr(t);
      if (s !== null && s !== undefined) {
        const def = plan.genericTitles?.includes(s.trim()) ? 'SITE.name' : J(s);
        edits.push({ start: title.value.start, end: title.value.end, text: `{ default: ${def}, template: \`%s — \${SITE.name}\` }` });
        what.push(plan.genericTitles?.includes(s.trim()) ? `title "${s}" → the brand` : 'title template (same default)');
      } else if (t.type === 'ObjectExpression' && !propOf(t, 'template')) {
        edits.push(insertProps(code, t, ['template: `%s — ${SITE.name}`']));
        what.push('title template');
      }
    }
    const desc = propOf(o, 'description');
    if (!desc) { add.push(prop('description', 'SITE.description')); what.push('description'); }
    else if (plan.genericDescriptions?.includes(litStr(desc.value))) { edits.push({ start: desc.value.start, end: desc.value.end, text: 'SITE.description' }); what.push('template description → the brief\'s'); }
    if (!propOf(o, 'applicationName')) add.push(prop('applicationName', 'SITE.name'));
    if (!propOf(o, 'openGraph')) { add.push(prop('openGraph', '{ type: "website", siteName: SITE.name, locale: SITE.locale }')); what.push('openGraph'); }
    if (!propOf(o, 'twitter')) { add.push(prop('twitter', '{ card: "summary_large_image" }')); what.push('twitter'); }
    if (!propOf(o, 'robots')) { add.push(prop('robots', 'NOINDEX ? { index: false, follow: false } : { index: true, follow: true }')); what.push('robots (noindex on previews)'); }
    if ((plan.verification?.google || plan.verification?.bing) && !propOf(o, 'verification')) {
      add.push(prop('verification', `{ ${[plan.verification.google ? `google: ${J(plan.verification.google)}` : '', plan.verification.bing ? `other: { "msvalidate.01": ${J(plan.verification.bing)} }` : ''].filter(Boolean).join(', ')} }`));
      what.push('search engine verification');
    }
    const alt = propOf(o, 'alternates');
    if (alt && multiPage) {
      const a = unwrap(alt.value);
      const c = propOf(a, 'canonical');
      if (c) {
        // a canonical in the ROOT layout is inherited by every page: every page would claim to be the home page
        edits.push(removeProp(code, a.properties.length === 1 ? alt : c));
        what.push('removed the inherited canonical (each page now declares its own)');
      }
    }
    if (add.length) edits.push(insertProps(code, o, add));
    if (edits.length) {
      code = applyEdits(code, edits);
      changes.push({ file, improved: what });
    }
  }
  // <html lang> and the JSON-LD script at the top of <body>
  m = moduleMeta(code, file);
  const edits = [];
  let htmlEl = null, bodyEl = null;
  walk(m.ast, (n) => {
    if (n.type === 'JSXElement' && jsxName(n.openingElement.name) === 'html') htmlEl = n;
    if (n.type === 'JSXElement' && jsxName(n.openingElement.name) === 'body') bodyEl = n;
    return true;
  });
  if (htmlEl && !attr(htmlEl.openingElement, 'lang')) {
    const nameEnd = htmlEl.openingElement.name.end;
    edits.push({ start: nameEnd, end: nameEnd, text: ` lang=${J((plan.site.languages || ['en'])[0])}` });
    changes.push({ file, added: `<html lang="${(plan.site.languages || ['en'])[0]}">` });
  }
  if (bodyEl && !code.includes('<JsonLd')) {
    const at = bodyEl.openingElement.end;
    edits.push({ start: at, end: at, text: `\n${lineIndent(code, bodyEl.start)}  <JsonLd data={JSON_LD} />` });
    changes.push({ file, added: 'JSON-LD (Organization/LocalBusiness + WebSite)' });
  }
  if (edits.length) code = applyEdits(code, edits);
  code = ensureNamedImport(code, file, siteSpec, ['SITE', 'NOINDEX', 'JSON_LD']);
  if (code.includes('<JsonLd')) code = ensureNamedImport(code, file, jsonLdSpec, ['JsonLd'], true);
  if (T && /:\s*Metadata\b/.test(code)) code = ensureNamedImport(code, file, 'next', ['Metadata'], true, true);
  return code;
}

function improvePage(prof, plan, page, code, changes) {
  const T = ts(prof);
  const p = plan.pages.find((x) => x.route === page.route) || { route: page.route };
  const brand = plan.site.name;
  const m = moduleMeta(code, page.file);
  if (m.client) { changes.push({ file: page.file, skipped: "'use client' page cannot export metadata — move the interactive part into a child component" }); return code; }
  if (m.gen) return code;
  const canonical = `alternates: { canonical: ${J(page.route)} }`;
  if (!m.meta) {
    const props = [];
    if (p.title) props.push(`title: ${titleExpr(p.title, brand)}`);
    if (p.description) props.push(`description: ${J(p.description)}`);
    props.push(canonical);
    if (p.noindex) props.push('robots: { index: false }');
    const imports = m.ast.program.body.filter((s) => s.type === 'ImportDeclaration');
    const at = imports.length ? imports[imports.length - 1].end : (m.ast.program.directives?.length ? m.ast.program.directives.at(-1).end : 0);
    const block = `export const metadata${T ? ': Metadata' : ''} = {\n  ${props.join(',\n  ')},\n};\n`;
    code = at ? code.slice(0, at) + '\n\n' + block + code.slice(at).replace(/^\n*/, '\n') : block + '\n' + code;
    if (T) code = ensureNamedImport(code, page.file, 'next', ['Metadata'], true, true);
    changes.push({ file: page.file, added: ['canonical', p.title && 'title', p.description && 'description'].filter(Boolean).join(', ') });
    return code;
  }
  const o = m.meta.obj;
  if (!o || o.type !== 'ObjectExpression') return code;
  const add = [], what = [];
  if (!propOf(o, 'title') && p.title) { add.push(`title: ${titleExpr(p.title, brand)}`); what.push('title'); }
  if (!propOf(o, 'description') && p.description) { add.push(`description: ${J(p.description)}`); what.push('description'); }
  const alt = propOf(o, 'alternates');
  const edits = [];
  if (!alt) { add.push(canonical); what.push('canonical'); }
  else if (!propOf(unwrap(alt.value), 'canonical') && unwrap(alt.value).type === 'ObjectExpression') {
    const a = unwrap(alt.value);
    edits.push(insertProps(code, a, [`canonical: ${J(page.route)}`]));
    what.push('canonical');
  }
  if (add.length) edits.push(insertProps(code, o, add));
  if (!edits.length) return code;
  changes.push({ file: page.file, improved: what });
  return applyEdits(code, edits);
}

function staticFiles(root, prof, plan, J_, changes) {
  const s = plan.site;
  const pages = plan.pages.filter((p) => !p.noindex);
  const disallow = [...new Set(['/api/', ...(plan.robots?.disallow || [])])];
  const training = plan.robots?.ai === 'search-only' ? plan.robots.training || [] : [];
  const robots = `# ${MARK} — written by deckhand (dh seo apply)\nUser-agent: *\nAllow: /\n${disallow.map((d) => `Disallow: ${d}`).join('\n')}\n`
    + (training.length ? `\n# the owner chose "search-only": model-training crawlers may not read the site\n${training.map((t) => `User-agent: ${t}`).join('\n')}\nDisallow: /\n` : '')
    + `\nSitemap: ${s.url}/sitemap.xml\n`;
  const sitemap = `<?xml version="1.0" encoding="UTF-8"?>\n<!-- ${MARK} -->\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${pages.map((p) => `  <url><loc>${s.url}${p.route === '/' ? '/' : p.route}</loc></url>`).join('\n')}\n</urlset>\n`;
  for (const [f, text] of [['public/robots.txt', robots], ['public/sitemap.xml', sitemap]]) {
    const abs = path.join(root, f);
    if (exists(abs) && !ours(read(abs))) { changes.push({ file: f, skipped: 'written by the owner — left as is (the audit reports what it lacks)' }); continue; }
    if (J_.write(f, text)) changes.push({ file: f, added: 'static' });
  }
}

function writeCommon(root, plan, J_, changes) {
  if (plan.llms) {
    const f = 'public/llms.txt';
    const abs = path.join(root, f);
    const text = plan.llms.trimEnd() + `\n\n<!-- ${MARK} -->\n`;
    if (!exists(abs) || ours(read(abs))) { if (J_.write(f, text)) changes.push({ file: f, added: 'llms.txt' }); }
  }
  if (plan.indexnow && /^[a-f0-9]{32,128}$/.test(plan.indexnow)) {
    const f = `public/${plan.indexnow}.txt`;
    if (J_.write(f, plan.indexnow)) changes.push({ file: f, added: 'IndexNow key file' });
  }
}

function indexHtml(root, plan, J_, changes) {
  const index = ['index.html', 'public/index.html'].find((x) => exists(path.join(root, x)));
  if (!index) return;
  let h = read(path.join(root, index));
  const s = plan.site;
  const home = plan.pages.find((p) => p.route === '/') || {};
  const tags = [];
  const title = home.title || s.name;
  const t = /<title>([^<]*)<\/title>/i.exec(h);
  if (!t) tags.push(`<title>${esc(title)}</title>`);
  else if (plan.genericTitles?.includes(t[1].trim())) h = h.replace(t[0], `<title>${esc(title)}</title>`);
  if (!/<meta\s+name=["']description["']/i.test(h) && (home.description || s.description)) tags.push(`<meta name="description" content="${esc(home.description || s.description)}" />`);
  if (!/rel=["']canonical["']/i.test(h)) tags.push(`<link rel="canonical" href="${esc(s.url)}/" />`);
  if (!/property=["']og:title["']/i.test(h)) tags.push(`<meta property="og:type" content="website" />`, `<meta property="og:title" content="${esc(title)}" />`, `<meta property="og:site_name" content="${esc(s.name)}" />`, `<meta property="og:url" content="${esc(s.url)}/" />`);
  if (!/name=["']twitter:card["']/i.test(h)) tags.push(`<meta name="twitter:card" content="summary_large_image" />`);
  if (!h.includes('application/ld+json')) tags.push(`<script type="application/ld+json">${JSON.stringify(plan.jsonld).replace(/</g, '\\u003c')}</script>`);
  if (tags.length) h = h.replace(/\n?[ \t]*<\/head>/i, `\n    ${tags.join('\n    ')}\n  </head>`);
  if (!/<html[^>]*\blang=/i.test(h)) h = h.replace(/<html\b/i, `<html lang="${(s.languages || ['en'])[0]}"`);
  if (J_.write(index, h)) changes.push({ file: index, added: 'head tags (title, description, canonical, Open Graph, twitter, JSON-LD, lang)' });
}
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

export function seoApply(rootIn, plan) {
  if (!plan || !plan.site || !plan.site.name || !plan.site.url) throw Object.assign(new Error('plan.site.name and plan.site.url are required'), { code: 'BAD_PLAN' });
  const prof = detectProject(rootIn);
  const root = prof.root;
  const J_ = journal(root);
  const changes = [];
  const insp = seoInspect(root);
  if (insp.router === 'app') {
    const A = prof.appDir;
    const libDir = path.posix.join(prof.codeRoot === '.' ? '' : prof.codeRoot, 'lib');
    const ext = ts(prof) ? '.ts' : '.js';
    const x = ts(prof) ? '.tsx' : '.jsx';
    // the site module: ours at lib/seo.ts, or beside an owner's own lib/seo.ts
    let siteFile = path.posix.join(libDir, 'seo' + ext);
    if (exists(path.join(root, siteFile)) && !ours(read(path.join(root, siteFile)))) siteFile = path.posix.join(libDir, 'seo.deckhand' + ext);
    const spec = (f) => specFor(prof, f) || './' + path.posix.relative(A, f).replace(/\.(tsx|ts|jsx|js)$/, '');
    const siteSpec = specFor(prof, siteFile) || null;
    const jsonLdFile = path.posix.join(prof.componentsDir, 'seo', 'json-ld' + x);
    if (!siteSpec) throw Object.assign(new Error('no import alias (tsconfig "paths" such as "@/*") — add one so generated files can import each other'), { code: 'NO_ALIAS' });
    if (J_.write(siteFile, siteModule(prof, plan))) changes.push({ file: siteFile, added: 'site facts + JSON-LD (from the brief)' });
    if (J_.write(jsonLdFile, jsonLdComponent(prof))) changes.push({ file: jsonLdFile, added: 'JsonLd component' });
    const owned = (key, file, text, what) => {
      const cur = insp.files[key];
      if (cur && !(cur === file && ours(read(path.join(root, cur))))) { changes.push({ file: cur, kept: `owner's ${what} (the audit checks it)` }); return; }
      if (J_.write(file, text)) changes.push({ file, added: what });
    };
    owned('robots', path.posix.join(A, 'robots' + ext), robotsModule(prof, plan, siteSpec), 'robots (crawl rules, AI crawlers, sitemap)');
    owned('sitemap', path.posix.join(A, 'sitemap' + ext), sitemapModule(prof, plan, siteSpec, insp.i18nSegment), 'sitemap (public routes from the plan)');
    owned('manifest', path.posix.join(A, 'manifest' + ext), manifestModule(prof, siteSpec), 'web app manifest');
    owned('ogImage', path.posix.join(A, 'opengraph-image' + x), ogModule(prof, siteSpec), 'Open Graph image 1200×630');
    owned('notFound', path.posix.join(A, 'not-found' + x), notFoundModule(prof), 'a real 404 page');
    const multiPage = insp.pages.filter((p) => !p.dynamic).length > 1;
    if (insp.layout) {
      const f = insp.layout.file;
      const code = read(path.join(root, f));
      const next = improveLayout(prof, plan, code, f, siteSpec, spec(jsonLdFile), changes, multiPage);
      if (next !== code) { parse(f, next); J_.write(f, next); }
    }
    for (const page of insp.pages) {
      if (page.dynamic) { if (!page.generateMetadata) changes.push({ file: page.file, todo: 'dynamic route: add generateMetadata (title, description, canonical per item)' }); continue; }
      if (page.error) { changes.push({ file: page.file, skipped: 'does not parse: ' + page.error }); continue; }
      const code = read(path.join(root, page.file));
      const next = improvePage(prof, plan, page, code, changes);
      if (next !== code) { parse(page.file, next); J_.write(page.file, next); }
    }
  } else if (insp.router === 'static' || insp.router === 'pages') {
    staticFiles(root, prof, plan, J_, changes);
    if (insp.router === 'static') indexHtml(root, plan, J_, changes);
  } else {
    throw Object.assign(new Error('no Next.js app, Vite or static index.html found — SEO files not written (the audit still reports what is missing)'), { code: 'UNSUPPORTED' });
  }
  writeCommon(root, plan, J_, changes);
  const written = J_.save();
  return { router: insp.router, written, changes, undo: written.length ? 'dh seo undo (byte-exact)' : null };
}

export function seoUndo(rootIn, { force = false } = {}) {
  const root = detectProject(rootIn).root;
  const p = path.join(root, '.deckhand', 'tryon', 'seo', 'last.json');
  if (!exists(p)) throw Object.assign(new Error('nothing to undo'), { code: 'NO_UNDO' });
  const last = JSON.parse(read(p));
  // byte-exact means back to before the apply: a file edited since would lose that edit, so it is the owner's call
  const edited = Object.keys(last.after || {}).filter((f) => shaOf(path.join(root, f)) !== last.after[f]);
  if (edited.length && !force) {
    throw Object.assign(new Error(`edited since the SEO apply: ${edited.join(', ')} — undo would lose those edits (seo undo --force to undo anyway)`), { code: 'FILE_CHANGED', files: edited });
  }
  for (const [f, before] of Object.entries(last.files)) {
    const abs = path.join(root, f);
    if (before === null) fs.rmSync(abs, { force: true });
    else fs.writeFileSync(abs, before);
  }
  fs.rmSync(p);
  return { restored: Object.keys(last.files), mode: 'byte-exact' };
}
