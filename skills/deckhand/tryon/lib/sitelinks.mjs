/**
 * sitelinks.mjs — a footer or navbar shows the site's own routes, never the design's demo menu.
 *
 * Source of truth, in order: copy.json (`footer.columns`, `footer.social`, `navbar.links`), then the
 * plan (`.deckhand/sitemap.json` nav.header / nav.footer, page titles as labels), then the brief's
 * `brand.social`. The design's literal link arrays are rewritten in place (AST-exact): flat menus get
 * the owner's routes, "GitHub / Discord / X" rows keep only the networks the owner really has (with the
 * design's icons), column menus get the owner's columns. Nothing is invented: with no source, the design's demo
 * menus and social rows are emptied (the owner's own links still reach the page through the content slots) —
 * a stranger's "Security · Partners · Jobs" or GitHub is never shown as the owner's.
 */
import fs from 'node:fs';
import path from 'node:path';
import { parse, walk } from './ast.cjs';

const LABEL_KEYS = ['label', 'name', 'title', 'text'];
// a footer column's title: `{ group: 'Product', items: [...] }` (Tailark) as well as `{ title, links }`
const COLUMN_KEYS = [...LABEL_KEYS, 'group', 'heading', 'category', 'section'];
const HREF_KEYS = ['href', 'url', 'link', 'to'];
const SOCIAL = /^(github|git hub|discord|slack|x|twitter|x \/ twitter|x\.com|linkedin|linked in|instagram|facebook|youtube|tiktok|threads|mastodon|bluesky|dribbble|behance|pinterest|reddit|telegram|whatsapp|twitch|medium|substack|rss)$/i;
const NETWORK = [
  ['x', /(^|\.)(x|twitter)\.com$/, /^(x|twitter|x \/ twitter|x\.com)$/i],
  ['github', /github\.com$/, /^git ?hub$/i], ['discord', /discord\.(gg|com)$/, /^discord$/i],
  ['slack', /slack\.com$/, /^slack$/i], ['linkedin', /linkedin\.com$/, /^linked ?in$/i],
  ['instagram', /instagram\.com$/, /^instagram$/i], ['facebook', /(facebook|fb)\.com$/, /^facebook$/i],
  ['youtube', /(youtube\.com|youtu\.be)$/, /^youtube$/i], ['tiktok', /tiktok\.com$/, /^tiktok$/i],
  ['threads', /threads\.net$/, /^threads$/i], ['bluesky', /bsky\.app$/, /^bluesky$/i],
  ['dribbble', /dribbble\.com$/, /^dribbble$/i], ['behance', /behance\.net$/, /^behance$/i],
  ['pinterest', /pinterest\.[a-z.]+$/, /^pinterest$/i], ['reddit', /reddit\.com$/, /^reddit$/i],
  ['telegram', /(t\.me|telegram\.org)$/, /^telegram$/i], ['whatsapp', /(wa\.me|whatsapp\.com)$/, /^whatsapp$/i],
  ['twitch', /twitch\.tv$/, /^twitch$/i], ['medium', /medium\.com$/, /^medium$/i], ['mastodon', /mastodon/, /^mastodon$/i],
];
const networkOfUrl = (u) => { try { const h = new URL(u).hostname.replace(/^www\./, ''); const n = NETWORK.find(([, rx]) => rx.test(h)); return n ? n[0] : null; } catch { return null; } };
const networkOfLabel = (l) => { const n = NETWORK.find(([, , rx]) => rx.test(String(l).trim())); return n ? n[0] : null; };

const readJson = (p) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; } };

/** The owner's links: { header[], footerCols[{title, links[]}], social[] } — or null when nothing is known. */
export function siteLinks(root, copy = {}) {
  const sm = readJson(path.join(root, '.deckhand', 'sitemap.json')) || {};
  const brief = readJson(path.join(root, '.deckhand', 'brief.json')) || {};
  const pages = new Map((sm.pages || []).map((p) => [p.route, p]));
  const resolve = (t) => {
    if (t && typeof t === 'object') return t.href ? { label: String(t.label || t.href), href: String(t.href) } : null;
    const s = String(t || '');
    if (s.startsWith('route:') || s.startsWith('/')) {
      const r = s.replace(/^route:/, '');
      if (r.includes('[')) return null;                      // a dynamic route is not a menu entry
      const p = pages.get(r);
      return { label: (p && p.title) || r, href: r };
    }
    if (/^mailto:/.test(s)) return { label: s.slice(7), href: s };
    if (/^tel:/.test(s)) return { label: s.slice(4), href: s };
    if (/^https?:\/\//.test(s)) { try { return { label: new URL(s).hostname.replace(/^www\./, ''), href: s }; } catch { return null; } }
    return null;
  };
  const list = (a) => [].concat(a || []).map(resolve).filter(Boolean);
  const nav = sm.nav || {};
  const header = (copy.navbar && copy.navbar.links ? list(copy.navbar.links) : list(nav.header)).filter((l) => l.href !== '/');
  let footerCols = null;
  const fc = copy.footer || {};
  if (Array.isArray(fc.columns) && fc.columns.length) footerCols = fc.columns.map((c) => ({ title: String(c.title || ''), links: list(c.links) }));
  else if (nav.footer && !Array.isArray(nav.footer) && typeof nav.footer === 'object') footerCols = Object.entries(nav.footer).map(([title, ts]) => ({ title, links: list(ts) }));
  else {
    // one column the owner's plan fully names: its menu + its footer links, titled with the brand
    const seen = new Set();
    const links = header.concat(list(nav.footer)).filter((l) => !seen.has(l.href) && seen.add(l.href));
    const brand = (brief.brand && brief.brand.name) || brief.name || '';
    if (links.length) footerCols = [{ title: brand, links }];
  }
  let social = fc.social || (brief.brand && brief.brand.social) || brief.social || [];
  if (social && !Array.isArray(social)) social = Object.entries(social).map(([k, v]) => ({ label: k, href: v }));
  social = [].concat(social).map((s) => (typeof s === 'string' ? { label: networkOfUrl(s) || s, href: s } : s)).filter((s) => s && s.href);
  if (!header.length && !footerCols && !social.length && !sm.nav) return null;
  return { header, footerCols: footerCols || [], social, known: !!(sm.nav || fc.columns || fc.social || brief.brand) };
}

const keyName = (p) => (p.key.type === 'Identifier' ? p.key.name : p.key.type === 'StringLiteral' ? p.key.value : null);
const strVal = (v) => (v && v.type === 'StringLiteral' ? v.value : v && v.type === 'TemplateLiteral' && !v.expressions.length ? v.quasis[0].value.cooked : null);
const unwrap = (n) => { while (n && /^TS(As|Satisfies)Expression$|^TSTypeAssertion$/.test(n.type)) n = n.expression; return n; };

function linkShape(o) {
  if (!o || o.type !== 'ObjectExpression') return null;
  let labelKey = null, hrefKey = null;
  for (const p of o.properties) {
    if (p.type !== 'ObjectProperty') continue;
    const k = keyName(p);
    if (!hrefKey && HREF_KEYS.includes(k) && strVal(p.value) != null) hrefKey = k;
    else if (!labelKey && LABEL_KEYS.includes(k) && strVal(p.value) != null) labelKey = k;
  }
  return labelKey && hrefKey ? { labelKey, hrefKey } : null;
}
const linkArray = (a) => {
  a = unwrap(a);
  if (!a || a.type !== 'ArrayExpression' || !a.elements.length) return null;
  const shapes = a.elements.map(linkShape);
  return shapes.every((s) => s && s.labelKey === shapes[0].labelKey && s.hrefKey === shapes[0].hrefKey) ? { arr: a, ...shapes[0] } : null;
};
function columnShape(o) {
  if (!o || o.type !== 'ObjectExpression') return null;
  let titleKey = null, linksKey = null, inner = null;
  for (const p of o.properties) {
    if (p.type !== 'ObjectProperty') continue;
    const k = keyName(p);
    if (!titleKey && COLUMN_KEYS.includes(k) && strVal(p.value) != null) titleKey = k;
    else if (!linksKey && linkArray(p.value)) { linksKey = k; inner = linkArray(p.value); }
  }
  return titleKey && linksKey ? { titleKey, linksKey, inner } : null;
}

/** Rewrite one object literal: new label/href, every other property kept (icons, ids). */
function relink(code, tpl, shape, l) {
  const rest = tpl.properties.filter((p) => !(p.type === 'ObjectProperty' && [shape.labelKey, shape.hrefKey].includes(keyName(p))))
    .map((p) => code.slice(p.start, p.end));
  return `{ ${shape.hrefKey}: ${JSON.stringify(l.href)}, ${shape.labelKey}: ${JSON.stringify(l.label)}${rest.length ? ', ' + rest.join(', ') : ''} }`;
}

/**
 * Fill the design's literal link arrays in `code` for a footer/navbar. Returns { code, filled[] }.
 * slot: 'footer' | 'navbar'. ts: emit typed empty arrays (a `[]` would type as never[]).
 */
export function fillLinks(file, code, links, slot, { ts = /\.tsx?$/.test(file) } = {}) {
  if (!['footer', 'navbar'].includes(slot)) return { code, filled: [] };
  links = links || { header: [], footerCols: [], social: [], known: false };
  let ast;
  try { ast = parse(file, code); } catch { return { code, filled: [] }; }
  const edits = [], filled = [];
  const empty = (shape) => (ts ? `([] as Array<{ ${shape.hrefKey}: string; ${shape.labelKey}: string; [k: string]: any }>)` : '[]');
  walk(ast, (n) => {
    if (n.type !== 'VariableDeclarator' || !n.init || n.id.type !== 'Identifier') return true;
    const init = unwrap(n.init);
    if (!init || init.type !== 'ArrayExpression' || !init.elements.length) return true;
    const name = n.id.name;
    const la = linkArray(init);
    if (la) {
      const labels = init.elements.map((e) => strVal(e.properties.find((p) => keyName(p) === la.labelKey).value));
      const social = labels.filter((l) => SOCIAL.test(l.trim()) || networkOfLabel(l)).length >= Math.ceil(labels.length / 2);
      if (social) {
        // keep the design's entries (and icons) for networks the owner is on; drop the rest (none known: none kept)
        const kept = [];
        init.elements.forEach((e, i) => {
          const net = networkOfLabel(labels[i]);
          const own = net && links.social.find((s) => (networkOfUrl(s.href) || networkOfLabel(s.label)) === net);
          if (own) kept.push(relink(code, e, la, { label: labels[i], href: own.href }));
        });
        edits.push({ start: n.init.start, end: n.init.end, text: kept.length ? `[${kept.join(', ')}]` : empty(la) });
        filled.push({ array: name, kind: 'social', count: kept.length });
      } else {
        const src = slot === 'navbar' ? links.header : links.footerCols.flatMap((c) => c.links);
        if (!src.length) {
          edits.push({ start: init.start, end: init.end, text: empty(la) });
          filled.push({ array: name, kind: 'menu', count: 0, demoHidden: labels.length });
          return false;
        }
        edits.push({ start: init.start, end: init.end, text: `[${src.map((l, i) => relink(code, init.elements[i % init.elements.length], la, l)).join(', ')}]` });
        filled.push({ array: name, kind: 'menu', count: src.length });
      }
      return false;
    }
    const shapes = init.elements.map(columnShape);
    const columns = slot === 'footer' && shapes.every((s) => s && s.titleKey === shapes[0].titleKey && s.linksKey === shapes[0].linksKey);
    if (columns && !links.footerCols.length) {
      const sh = shapes[0], inner = sh.inner;
      edits.push({ start: init.start, end: init.end, text: ts ? `([] as Array<{ ${sh.titleKey}: string; ${sh.linksKey}: Array<{ ${inner.hrefKey}: string; ${inner.labelKey}: string; [k: string]: any }>; [k: string]: any }>)` : '[]' });
      filled.push({ array: name, kind: 'columns', count: 0, demoHidden: init.elements.length });
      return false;
    }
    if (columns) {
      const sh = shapes[0];
      const cols = links.footerCols.map((c, ci) => {
        const tpl = init.elements[ci % init.elements.length];
        const inner = shapes[ci % shapes.length].inner;
        const arr = c.links.length ? `[${c.links.map((l, i) => relink(code, inner.arr.elements[i % inner.arr.elements.length], inner, l)).join(', ')}]` : empty(inner);
        const rest = tpl.properties.filter((p) => !(p.type === 'ObjectProperty' && [sh.titleKey, sh.linksKey].includes(keyName(p)))).map((p) => code.slice(p.start, p.end));
        return `{ ${sh.titleKey}: ${JSON.stringify(c.title)}, ${sh.linksKey}: ${arr}${rest.length ? ', ' + rest.join(', ') : ''} }`;
      });
      edits.push({ start: init.start, end: init.end, text: `[${cols.join(', ')}]` });
      filled.push({ array: name, kind: 'columns', count: cols.length });
      return false;
    }
    return true;
  });
  if (!edits.length) return { code, filled };
  edits.sort((a, b) => b.start - a.start);
  let out = code;
  for (const e of edits) out = out.slice(0, e.start) + e.text + out.slice(e.end);
  return { code: out, filled };
}

/** Every word the owner's links put on the page (so the demo-copy ledger never flags them). */
export const linkTexts = (links) => (links ? [...links.header.map((l) => l.label), ...links.footerCols.flatMap((c) => [c.title, ...c.links.map((l) => l.label)]), ...links.social.map((s) => s.label)] : []);

/** Slots whose form IS the purpose (the plan wires it); every other design form is hidden by default. */
export const FORM_SLOTS = new Set(['contact', 'login', 'signup', 'forgot-password', 'newsletter', 'input', 'textarea', 'select', 'checkbox', 'switch', 'radio-group']);
