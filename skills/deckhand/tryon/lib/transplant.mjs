/**
 * transplant.mjs — "their design, your words", deterministically (no model call).
 *
 * extractUnits(): the clicked JSX subtree -> content units in document order. A unit is the
 *   nearest content-bearing element (h1-h6, p, a/Link/Button, li, label, blockquote …); its source is
 *   the deepest element holding all the text (so icons beside a label survive), taken VERBATIM:
 *   inner markup and in-scope expressions like {t('title')} are carried as-is.
 *   Lists rendered with `arr.map(…)` over a literal array in the same file are UNROLLED: each
 *   item's fields are evaluated, so a pricing grid carries every plan, price and feature.
 * parameterize(): the candidate component -> slots. Static units become
 *   `{content.heading1 ?? <>demo</>}`; a `.map()` over the candidate's own demo array becomes a
 *   list slot `(content.list1 ? content.list1.map(merge-with-demo) : demo).map(…)`.
 * bind(): pair units by role and order; pair lists item by item, field by role.
 * The usage replaces the clicked element in place, so every carried expression stays in scope.
 */
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { parse, walk, jsxName, attr } = require('./ast.cjs');

const BLOCK_TAGS = new Set(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'a', 'button', 'li', 'label', 'blockquote',
  'figcaption', 'dt', 'dd', 'td', 'th', 'cite', 'q', 'legend', 'summary', 'caption', 'option']);

export function roleOf(name) {
  if (/^h[1-6]$/.test(name)) return 'heading';
  // compound components (shadcn/Radix naming): CardTitle, AccordionTrigger, DialogDescription …
  if (/[a-z](Title|Trigger|Heading|Question|Label)$/.test(name)) return /Label$/.test(name) ? 'label' : 'heading';
  if (/[a-z](Description|Content|Answer|Body|Text|Subtitle)$/.test(name)) return 'text';
  if (/^(a|button)$/.test(name) || /(^|\.)(Link|Button|NavLink|Anchor)$/.test(name) || /Button$/.test(name)) return 'action';
  if (name === 'summary' || name === 'dt') return 'heading';           // a FAQ question: <details><summary>, <dl><dt>
  if (name === 'dd') return 'text';
  if (name === 'li') return 'item';
  if (name === 'label' || name === 'legend') return 'label';
  if (/^(blockquote|q)$/.test(name)) return 'quote';
  if (/^(cite|figcaption)$/.test(name)) return 'text';                 // who said it: a name line, not the quote
  return 'text';
}
const COMPOUND = /[a-z](Title|Trigger|Heading|Question|Label|Description|Content|Answer|Body|Text|Subtitle)$/;
const isBlockEl = (name) => BLOCK_TAGS.has(name) || roleOf(name) === 'action' || COMPOUND.test(name);
const CONTENT_ROLES = ['heading', 'text', 'price', 'figure', 'action', 'item', 'label', 'quote', 'copyright'];
const ITEM_CLASSES = [['heading', 'text', 'quote', 'label', 'figure'], ['price'], ['action'], ['item']];
const PRICE = /^(?:from\s+)?[$€£¥₹]?\s?\d[\d.,\s]*(?:k)?\s?(?:[$€£¥₹]|eur|usd|mad|dh)?\s*(?:\/\s*\w+|per \w+)?$/i;
const COPYRIGHT = /^(©|\(c\)|copyright\b)/i;
/** A figure — 120+, 98%, 24h, 7/7, 10M+, 4.9x, +500, 22 Million — the number of a stat, never a price or a word. */
const FIGURE = /^[+~]?\s?\d[\d.,]*\s?(?:%|\+|[kmb]\+?|x|h|\/\s?\d+|\s(?:million|billion|thousand)\+?)$|^\+\s?\d[\d.,]*$/i;
const isFigure = (t) => FIGURE.test(String(t).trim()) && String(t).trim().length <= 16;
const withPrice = (u) => {
  if (u.role !== 'action' && COPYRIGHT.test(u.text)) return { ...u, role: 'copyright' };
  if (u.role !== 'action' && isFigure(u.text)) return { ...u, role: 'figure' };
  return u.role !== 'action' && u.role !== 'heading' && PRICE.test(u.text) ? { ...u, role: 'price' } : u;
};

const isStaticExpr = (e) => e.type === 'StringLiteral' || (e.type === 'TemplateLiteral' && !e.expressions.length);
const SAFE_GLOBALS = new Set(['Date', 'Math', 'Intl', 'String', 'Number', 'JSON', 'undefined']);
/** `{2026}`, `{new Date().getFullYear()}`: an expression that refers to nothing in its file renders like text — a
 *  design's `© {2026} Acme` line is a slot like any other (it was left on the owner's page as demo copy). */
function selfContained(e) {
  if (!e || e.type === 'JSXEmptyExpression') return false;
  let ok = true;
  walk(e, (n, parent, key) => {
    if (!ok) return false;
    if (n.type === 'JSXElement' || n.type === 'JSXFragment' || /Function/.test(n.type)) return (ok = false);
    if (n.type === 'Identifier' && !(parent && parent.type === 'MemberExpression' && key === 'property' && !parent.computed) && !SAFE_GLOBALS.has(n.name)) return (ok = false);
    return true;
  });
  return ok;
}

function hasStaticText(kids) {
  return kids.some((c) => (c.type === 'JSXText' && c.value.trim()) || (c.type === 'JSXExpressionContainer' && isStaticExpr(c.expression)));
}
/** An expression that renders content (`{t('x')}`, `{p.name}`) — not structure (`{list.map(…)}`, `{ok && <X/>}`). */
function isDynamicChild(c) {
  if (c.type !== 'JSXExpressionContainer' || c.expression.type === 'JSXEmptyExpression' || isStaticExpr(c.expression) || selfContained(c.expression)) return false;
  let structural = false;
  walk(c.expression, (n) => {
    if (structural) return false;
    if (n.type === 'JSXElement' || n.type === 'JSXFragment' || /Function/.test(n.type) || mapCall(n)) return (structural = true, false);
    return true;
  });
  return !structural;
}
function childExpressions(el) {
  return (el.children || []).some((c) => isDynamicChild(c) || (c.type === 'JSXElement' && childExpressions(c)));
}
function directContent(kids, dyn) { return hasStaticText(kids) || (dyn && kids.some(isDynamicChild)); }
function inlineContent(el, dyn) {
  const kids = el.children || [];
  if (directContent(kids, dyn)) return true;
  return kids.some((c) => c.type === 'JSXElement' && !isBlockEl(jsxName(c.openingElement.name)) && inlineContent(c, dyn));
}
/** Deepest element holding ALL the text: `<Link><span>Go</span><Icon/></Link>` -> span. */
function textHost(el, dyn) {
  const kids = el.children || [];
  if (directContent(kids, dyn)) return el;
  const bearing = kids.filter((c) => c.type === 'JSXElement' && inlineContent(c, dyn));
  return bearing.length === 1 ? textHost(bearing[0], dyn) : el;
}
function containsBlock(el) {
  let found = false;
  walk(el, (n) => {
    if (found) return false;
    if (n.type === 'JSXElement' && isBlockEl(jsxName(n.openingElement.name)) && inlineContent(n, true)) return (found = true, false);
    return true;
  });
  return found;
}
/** A call to action (a Button, or a filled/padded host button) vs a plain text link (nav, eyebrow pill). */
function actionKind(outer) {
  const name = jsxName(outer.openingElement.name);
  if (/Button$/.test(name) || name === 'button') return 'cta';
  const cls = (() => { const a = attr(outer, 'className'); return a && a.value && a.value.type === 'StringLiteral' ? a.value.value : ''; })();
  if (/^[a-z]/.test(name) && /\bbg-(?!transparent|muted|background)/.test(cls) && /\b(px|py|p)-\d/.test(cls)) return 'cta';
  return 'link';
}

/** Index range [a, b] of children that carry text; icons/whitespace at either end are left alone. */
function textRange(kids) {
  const hasText = (c) => (c.type === 'JSXText' && c.value.trim()) || (c.type === 'JSXExpressionContainer' && c.expression.type !== 'JSXEmptyExpression'
    && !(isStaticExpr(c.expression) && !String(c.expression.value ?? c.expression.quasis?.[0]?.value?.cooked ?? '').trim()))
    || (c.type === 'JSXElement' && inlineContent(c, true));
  let a = 0, b = kids.length - 1;
  while (a <= b && !hasText(kids[a])) a++;
  while (b >= a && !hasText(kids[b])) b--;
  return [a, b];
}

/** `<Button asChild><Link href="/x">…` — the href lives on the single child element. */
function findHref(el) {
  const own = attr(el, 'href') || attr(el, 'to');
  if (own) return own;
  const kids = (el.children || []).filter((c) => c.type === 'JSXElement');
  return kids.length === 1 ? findHref(kids[0]) : null;
}

function textOf(code, node) {
  let s = '';
  walk(node, (n, parent) => {
    if (n.type === 'JSXAttribute') return false;
    if (n.type === 'JSXText') s += n.value;
    else if (n.type === 'JSXExpressionContainer' && parent && parent.type !== 'JSXAttribute') {
      const e = n.expression;
      if (e.type === 'StringLiteral') s += e.value;
      else if (e.type === 'NumericLiteral') s += String(e.value);
      else if (e.type !== 'JSXEmptyExpression') s += '{' + code.slice(e.start, e.end) + '}';
      return false;
    }
    return true;
  });
  return s.replace(/\s+/g, ' ').trim();
}

/* ------------------------------------------------------------------ literal data */

/** JS value of a literal AST node; undefined when anything is non-literal. */
export function litValue(node) {
  if (!node) return undefined;
  switch (node.type) {
    case 'StringLiteral': case 'NumericLiteral': case 'BooleanLiteral': return node.value;
    case 'TemplateLiteral': return node.expressions.length ? undefined : node.quasis.map((q) => q.value.cooked).join('');
    case 'TSAsExpression': case 'TSSatisfiesExpression': case 'TSConstAssertion': return litValue(node.expression);
    case 'ArrayExpression': {
      const out = [];
      for (const e of node.elements) { const v = litValue(e); out.push(v); }
      return out;
    }
    case 'ObjectExpression': {
      const o = {};
      for (const p of node.properties) {
        if (p.type !== 'ObjectProperty' || p.computed) continue;
        const k = p.key.type === 'Identifier' ? p.key.name : p.key.value;
        o[k] = litValue(p.value);                      // non-literal fields become undefined (icons, components)
      }
      return o;
    }
    default: return undefined;
  }
}

/** Literal arrays by name — module level AND inside component bodies (Tailark keeps FAQ data there). */
function topArrays(ast) {
  const m = new Map();
  walk(ast, (n) => {
    if (n.type !== 'VariableDeclarator' || n.id.type !== 'Identifier') return true;
    let init = n.init;
    while (init && /^TS(As|Satisfies)Expression$/.test(init.type)) init = init.expression;
    if (init && init.type === 'ArrayExpression' && !m.has(n.id.name)) m.set(n.id.name, init);
    return true;
  });
  return m;
}

function mapCall(e) {
  if (e.type !== 'CallExpression' || e.callee.type !== 'MemberExpression' || e.callee.property.name !== 'map') return null;
  const cb = e.arguments[0];
  if (!cb || !/Function/.test(cb.type)) return null;
  return { object: e.callee.object, cb };
}

function binding(cb) {
  const p = cb.params[0];
  if (!p) return null;
  if (p.type === 'Identifier') return { kind: 'id', name: p.name };
  if (p.type === 'ObjectPattern') {
    const map = {};
    for (const pr of p.properties) {
      if (pr.type !== 'ObjectProperty') continue;
      const key = pr.key.name || pr.key.value;
      const local = pr.value.type === 'Identifier' ? pr.value.name : (pr.value.type === 'AssignmentPattern' && pr.value.left.type === 'Identifier' ? pr.value.left.name : null);
      if (local) map[local] = key;
    }
    return { kind: 'obj', map };
  }
  return null;
}

/** Field name an expression reads from the map item (`p.name`, destructured `name`), else null. */
function fieldOf(e, bind) {
  if (!bind || !e) return null;
  if (bind.kind === 'id' && e.type === 'MemberExpression' && !e.computed && e.object.type === 'Identifier' && e.object.name === bind.name) return e.property.name;
  if (bind.kind === 'obj' && e.type === 'Identifier' && bind.map[e.name]) return bind.map[e.name];
  return null;
}

function callbackJsx(cb) {
  const out = [];
  if (cb.body.type !== 'BlockStatement') {
    walk(cb.body, (n) => { if (n.type === 'JSXElement') { out.push(n); return false; } return true; });
  } else {
    walk(cb.body, (n) => {
      if (n !== cb.body && /Function/.test(n.type)) return false;
      if (n.type === 'ReturnStatement' && n.argument) { walk(n.argument, (m) => { if (m.type === 'JSXElement') { out.push(m); return false; } return true; }); return false; }
      return true;
    });
  }
  return out;
}

const escapeJsxText = (s) => (/[{}<>]/.test(s) ? `{${JSON.stringify(s)}}` : s);

/** Source of `host`'s children with every item-field expression replaced by its literal. */
function resolvedSrc(code, host, env) {
  const kids = host.children || [];
  if (!kids.length) return null;
  const edits = [];
  let ok = true;
  walk({ type: 'X', children: kids }, (n, parent) => {
    if (!ok) return false;
    if (n.type === 'JSXAttribute') return false;
    if (n.type === 'JSXExpressionContainer' && parent && parent.type !== 'JSXAttribute') {
      const e = n.expression;
      if (e.type === 'JSXEmptyExpression' || isStaticExpr(e)) return false;
      const f = fieldOf(e, env.bind);
      const v = f != null ? env.item[f] : undefined;
      if (typeof v === 'string' || typeof v === 'number') edits.push({ start: n.start, end: n.end, text: escapeJsxText(String(v)) });
      else ok = false;
      return false;
    }
    return true;
  });
  if (!ok) return null;
  let s = code.slice(kids[0].start, kids[kids.length - 1].end);
  const base = kids[0].start;
  edits.sort((a, b) => b.start - a.start);
  for (const e of edits) s = s.slice(0, e.start - base) + e.text + s.slice(e.end - base);
  return s;
}

function resolvedText(src) {
  return src.replace(/<[^>]+>/g, ' ').replace(/\{"(.*?)"\}/g, '$1').replace(/\s+/g, ' ').trim();
}

/* ------------------------------------------------------------------ collection */

/**
 * Walk a JSX root. mode 'original': expressions allowed, literal-array maps unrolled.
 * mode 'candidate': static units only; maps over demo arrays become list slots.
 */
function collect(code, root, ast, mode) {
  const arrays = topArrays(ast);
  const units = [], images = [], inputs = [], lists = [], bullets = [];
  let dynamicLists = 0;

  const unitFor = (el, env) => {
    const name = jsxName(el.openingElement.name);
    const dyn = mode === 'original';
    const host = textHost(el, dyn || !!env);
    const hk = host.children || [];
    if (!hk.length) return null;
    const hrefAttr = findHref(el);
    const level = /^h([1-6])$/.exec(name);
    const base = { role: roleOf(name), level: level ? Number(level[1]) : null, el, tag: name, host };
    if (env) {
      const src = resolvedSrc(code, host, env);
      if (src == null || !src.trim()) return null;
      let href = null;
      if (hrefAttr && hrefAttr.value) {
        if (hrefAttr.value.type === 'StringLiteral') href = JSON.stringify(hrefAttr.value.value);
        else if (hrefAttr.value.type === 'JSXExpressionContainer') {
          const f = fieldOf(hrefAttr.value.expression, env.bind);
          if (f != null && typeof env.item[f] === 'string') href = JSON.stringify(env.item[f]);
        }
      }
      return { ...base, src: src.trim(), text: resolvedText(src), href, dynamic: false };
    }
    const dynamic = childExpressions(host);
    if (mode === 'candidate' && dynamic) return null;
    // the replaceable range skips icons at either end (`<Icon/> Label` / `Label <Chevron/>`)
    const [a, b] = textRange(hk);
    if (a > b) return null;
    const src = code.slice(hk[a].start, hk[b].end);
    if (!src.trim()) return null;
    return { ...base, childrenStart: hk[a].start, childrenEnd: hk[b].end, src, text: textOf(code, host), dynamic, hrefAttr };
  };

  // `<p><span><Icon/> Title.</span>{' '}Description</p>` is TWO slots: a lead (heading) and a body
  const leadBody = (el) => {
    const kids = (el.children || []).filter((c) => !(c.type === 'JSXText' && !c.value.trim()) && !(c.type === 'JSXExpressionContainer' && isStaticExpr(c.expression) && !String(c.expression.value ?? '').trim()));
    if (kids.length < 2 || kids[0].type !== 'JSXElement') return null;
    const lead = kids[0];
    const ln = jsxName(lead.openingElement.name);
    if (isBlockEl(ln) || !inlineContent(lead, mode === 'original')) return null;
    const rest = kids.slice(1);
    if (!rest.every((c) => c.type === 'JSXText' || (c.type === 'JSXExpressionContainer' && (mode === 'original' || isStaticExpr(c.expression))) || (c.type === 'JSXElement' && !isBlockEl(jsxName(c.openingElement.name))))) return null;
    if (!rest.some((c) => c.type === 'JSXText' && c.value.trim())) return null;
    const lu = unitFor(lead, null);
    if (!lu) return null;
    // the body range starts at its first word: a `<br />` or the separating space stays in the design
    let i0 = 0;
    while (i0 < rest.length - 1 && rest[i0].type === 'JSXElement' && jsxName(rest[i0].openingElement.name) === 'br') i0++;
    const first = rest[i0], last = rest[rest.length - 1];
    const bodyStart = first.type === 'JSXText' ? first.start + (first.value.length - first.value.trimStart().length) : first.start;
    const bodyEnd = last.type === 'JSXText' ? last.end - (last.value.length - last.value.trimEnd().length) : last.end;
    const bsrc = code.slice(bodyStart, bodyEnd);
    const lvl = /^h([1-6])$/.exec(jsxName(el.openingElement.name));
    // `<p><span>99.9%</span> Uptime guarantee.</p>` leads with a figure, not a title
    return [{ ...lu, role: isFigure(lu.text) ? 'figure' : 'heading', sub: 'lead', el: lead, level: lvl ? Number(lvl[1]) : lu.level },
      { role: 'text', level: null, el, tag: jsxName(el.openingElement.name), host: el, childrenStart: bodyStart, childrenEnd: bodyEnd,
        src: bsrc, text: bsrc.replace(/<[^>]+>/g, ' ').replace(/\{\s*['"] ?['"]\s*\}/g, ' ').replace(/\s+/g, ' ').trim(), dynamic: false, hrefAttr: null,
        // a two-tone heading's muted half: the owner's subtitle if one is left over, else nothing
        ...(lvl || roleOf(jsxName(el.openingElement.name)) === 'heading' ? { optional: true } : {}) }];
  };

  // Words written straight into an element that also holds a link or button. One run of them (before or after the
  // link) is a line of text and the link stays an action; words on both sides of a link are one sentence, carried
  // whole with the link inside it.
  const mixedText = (el, name, kids) => {
    if (!/^[a-z]/.test(name) || /^(svg|path|g|code|pre|kbd|option|select|ul|ol|nav|form)$/.test(name) || !hasStaticText(kids)) return null;
    const inline = (c) => c.type === 'JSXText' || (c.type === 'JSXExpressionContainer' && (c.expression.type === 'JSXEmptyExpression' || isStaticExpr(c.expression) || isDynamicChild(c)))
      || (c.type === 'JSXElement' && !isBlockEl(jsxName(c.openingElement.name)) && !containsBlock(c));
    const runs = [];
    let cur = null;
    kids.forEach((c, i) => { if (inline(c)) { if (!cur) runs.push(cur = []); cur.push(i); } else cur = null; });
    const letters = (idx) => idx.reduce((n, i) => { const c = kids[i]; const t = c.type === 'JSXText' ? c.value : c.type === 'JSXExpressionContainer' && isStaticExpr(c.expression) ? String(c.expression.value ?? c.expression.quasis?.[0]?.value?.cooked ?? '') : c.type === 'JSXElement' ? textOf(code, c) : ''; return n + (t.match(/[\p{L}\p{N}]/gu) || []).length; }, 0);
    const worded = runs.filter((r) => letters(r) >= 4);
    if (!worded.length) return null;
    const linkLike = (c) => c.type === 'JSXText' || c.type === 'JSXExpressionContainer' || (c.type === 'JSXElement' && /^(a|Link|NavLink|Anchor)$/.test(jsxName(c.openingElement.name).split('.').pop()) && actionKind(c) === 'link');
    const spans = worded.length > 1 && kids.slice(worded[0][0], worded[worded.length - 1].slice(-1)[0] + 1).every(linkLike)
      ? [[worded[0][0], worded[worded.length - 1].slice(-1)[0]]] : worded.map((r) => [r[0], r[r.length - 1]]);
    const used = new Set(), out = [];
    for (const [a, b] of spans) {
      const first = kids[a], last = kids[b];
      const s = first.type === 'JSXText' ? first.start + (first.value.length - first.value.trimStart().length) : first.start;
      const e = last.type === 'JSXText' ? last.end - (last.value.length - last.value.trimEnd().length) : last.end;
      if (e <= s) continue;
      const src = code.slice(s, e);
      const part = kids.slice(a, b + 1);
      part.forEach((c) => used.add(c));
      const level = /^h([1-6])$/.exec(name);
      out.push({ role: roleOf(name) === 'action' ? 'text' : roleOf(name), level: level ? Number(level[1]) : null, el, tag: name, host: el,
        childrenStart: s, childrenEnd: e, src, text: textOf(code, { type: 'JSXFragment', children: part }),
        dynamic: part.some((c) => isDynamicChild(c) || (c.type === 'JSXElement' && childExpressions(c))), hrefAttr: null });
    }
    return out.length ? { units: out.map(withPrice), used } : null;
  };

  const visit = (el, ctx) => {
    if (el.type !== 'JSXElement') return;
    const name = jsxName(el.openingElement.name);
    if (/^(style|script|noscript|template)$/.test(name)) return;
    if (roleOf(name) === 'action' && !ctx.actionOuter) ctx = { ...ctx, actionOuter: el };
    if (/^(img|Image)$/.test(name)) {
      const src = attr(el, 'src'), alt = attr(el, 'alt');
      if (src && src.value) {
        if (ctx.env) {
          const val = (a) => {
            if (!a || !a.value) return null;
            if (a.value.type === 'StringLiteral') return JSON.stringify(a.value.value);
            const f = a.value.type === 'JSXExpressionContainer' ? fieldOf(a.value.expression, ctx.env.bind) : null;
            return f != null && typeof ctx.env.item[f] === 'string' ? JSON.stringify(ctx.env.item[f]) : null;
          };
          ctx.item.images.push({ src: val(src), alt: val(alt) });
        } else if (!ctx.inMap) images.push({ el, src, alt, parent: ctx.parent || null, grand: ctx.grand || null });
      }
    }
    if (/^(input|textarea|Input|Textarea)$/.test(name) && !ctx.inMap && !ctx.env) {
      const ph = attr(el, 'placeholder');
      if (ph && ph.value) inputs.push({ el, ph });
    }
    const kids = el.children || [];
    const nestedBlock = kids.some((c) => c.type === 'JSXElement' && containsBlock(c));
    const blockish = isBlockEl(name) && !nestedBlock && inlineContent(el, mode === 'original' || !!ctx.env);
    // a div/span that holds text directly (a price, a tagline) is content too — decorative bits are not
    const loose = !blockish && !nestedBlock && /^[a-z]/.test(name) && !/^(svg|path|g|circle|rect|code|pre|kbd|option|style|script|noscript|template)$/.test(name)
      && directContent(kids, mode === 'original' || !!ctx.env);
    // `<h2><span class="text-foreground">Lead.</span><br/> muted rest</h2>` (two-tone heading) splits too
    if (blockish && !ctx.env && !ctx.inMap && (/^(text|item)$/.test(roleOf(name)) || (mode === 'candidate' && roleOf(name) === 'heading'))) {
      const pair = leadBody(el);
      if (pair) { for (const u of pair) units.push(u); return; }
    }
    // `New: weekend deep-cleans. <Link>Book a slot</Link>`: the words beside a link or button are the owner's too
    const skip = mode === 'original' && !ctx.inMap && !ctx.env && !blockish && nestedBlock ? mixedText(el, name, kids) : null;
    if (skip) {
      for (const u of skip.units) units.push(u);
      for (const c of kids) {
        if (skip.used.has(c)) continue;
        if (c.type === 'JSXElement') visit(c, ctx);
        else if (c.type === 'JSXExpressionContainer') visitExpr(c.expression, ctx);
      }
      return;
    }
    if (blockish || loose) {
      if (!ctx.inMap || ctx.env) {
        let u = unitFor(el, ctx.env);
        if (u) u = withPrice(u);
        if (u && loose && u.role !== 'price' && u.role !== 'figure' && u.text.replace(/[^\p{L}\p{N}]/gu, '').length < 4) u = null;
        if (u) {
          if (u.role === 'action') { u.outer = ctx.actionOuter || el; u.sub = actionKind(u.outer); }
          if (ctx.env) { u.list = ctx.list; u.itemIdx = ctx.itemIdx; u.tpl = el; ctx.item.units.push(u); }
          units.push(u);
          return;
        }
      }
    }
    const down = { ...ctx, parent: el, grand: ctx.parent || null };
    for (const c of kids) {
      if (c.type === 'JSXElement') visit(c, down);
      else if (c.type === 'JSXFragment') { for (const cc of c.children) if (cc.type === 'JSXElement') visit(cc, down); }
      else if (c.type === 'JSXExpressionContainer') visitExpr(c.expression, down);
    }
  };

  const visitExpr = (e, ctx) => {
    const mc = mapCall(e);
    if (mc) {
      const arr = mc.object.type === 'Identifier' ? arrays.get(mc.object.name) : (mc.object.type === 'ArrayExpression' ? mc.object : null);
      const bind = binding(mc.cb);
      const roots = callbackJsx(mc.cb);
      // nested list inside a list item: `p.features.map(f => <li>{f}</li>)`
      if (ctx.env && mc.object.type === 'MemberExpression') {
        const f = fieldOf(mc.object, ctx.env.bind);
        const vals = f != null ? ctx.env.item[f] : undefined;
        if (Array.isArray(vals) && vals.every((v) => typeof v === 'string')) ctx.item.bullets.push(...vals);
        return;
      }
      if (mode === 'original' && arr && !ctx.env && bind) {
        const items = litValue(arr);
        if (Array.isArray(items) && items.length && items.every((x) => x && typeof x === 'object')) {
          const list = { items: [] };
          lists.push(list);
          items.forEach((item, i) => {
            const it = { units: [], images: [], bullets: [] };
            list.items.push(it);
            for (const r of roots) visit(r, { env: { bind, item }, list, itemIdx: i, item: it });
          });
          return;
        }
      }
      if (mode === 'candidate' && mc.object.type === 'ArrayExpression' && !ctx.inMap) {
        const vals = litValue(mc.object);
        if (Array.isArray(vals) && vals.length && vals.every((v) => typeof v === 'string')) bullets.push({ node: mc.object, count: vals.length });
      }
      if (mode === 'candidate' && arr && mc.object.type === 'Identifier' && !ctx.inMap && bind) {
        const demo = litValue(arr);
        if (Array.isArray(demo) && demo.length && demo.every((x) => x && typeof x === 'object')) {
          const fields = listFields(code, roots, bind).map((f) => {
            const v = typeof demo[0][f.field] === 'string' ? demo[0][f.field].trim() : null;
            if (v != null && ['text', 'item', 'heading'].includes(f.role) && isFigure(v)) return { ...f, role: 'figure' };
            return ['text', 'item'].includes(f.role) && v != null && PRICE.test(v) ? { ...f, role: 'price' } : f;
          });
          // a card template's own button label ("Get Started" in every plan): an action field of its own, so the
          // owner's "Add to cart" goes there instead of being dropped (the design's words stay only as a dashed fallback)
          const consts = [];
          if (bind.kind === 'id' && !fields.some((f) => f.role === 'action')) {
            for (const r of roots) walk(r, (n) => {
              if (consts.length || n.type !== 'JSXElement') return !consts.length;
              if (roleOf(jsxName(n.openingElement.name)) !== 'action') return true;
              const host = textHost(n, true), hk = host.children || [];
              const [a, b] = textRange(hk);
              if (a > b) return false;
              const part = hk.slice(a, b + 1);
              // "Get Started", or `{tier.price === 'Custom' ? 'Contact Us' : 'Get Started'}` (words in both branches)
              const choice = part.length === 1 && part[0].type === 'JSXExpressionContainer' && part[0].expression.type === 'ConditionalExpression'
                && [part[0].expression.consequent, part[0].expression.alternate].every(isStaticExpr);
              if (!choice && !part.every((c) => c.type === 'JSXText')) return false;
              const s0 = choice ? part[0].start : hk[a].start + (hk[a].value.length - hk[a].value.trimStart().length);
              const e0 = choice ? part[0].end : hk[b].end - (hk[b].value.length - hk[b].value.trimEnd().length);
              consts.push({ start: s0, end: e0, text: code.slice(s0, e0), param: bind.name });
              return false;
            });
            if (consts.length) fields.push({ field: 'dhAction', role: 'action', constant: true });
          }
          lists.push({ name: mc.object.name, object: mc.object, fields, demoCount: demo.length,
            demoItems: demo, textOnly: textOnlyFields(roots, bind), consts });
        }
      }
      if (mode === 'original' && !ctx.env) dynamicLists++;
      for (const r of roots) visit(r, { ...ctx, inMap: true });
      return;
    }
    walk(e, (n) => {
      if (n.type === 'JSXElement') { visit(n, ctx); return false; }
      if (n !== e && mapCall(n)) { visitExpr(n, ctx); return false; }
      return true;
    });
  };

  if (root.type === 'JSXFragment') for (const c of root.children) { if (c.type === 'JSXElement') visit(c, {}); else if (c.type === 'JSXExpressionContainer') visitExpr(c.expression, {}); }
  else visit(root, {});
  return { units, images, inputs, lists, bullets, dynamicLists };
}

/**
 * The item fields a design only ever renders as the text of an element (`<h3>{item.question}</h3>`), never as a
 * key, prop or attribute: those can carry a dashed demo marker instead of a bare string.
 */
function textOnlyFields(roots, bind) {
  const uses = new Map(), asText = new Map();
  const fieldOfMember = (m) => fieldOf(m, bind);
  for (const r of roots) {
    walk(r, (n, parent, key) => {
      const f = fieldOfMember(n);
      if (f) {
        uses.set(f, (uses.get(f) || 0) + 1);
        if (parent && parent.type === 'JSXExpressionContainer' && key === 'expression') asText.set(f, (asText.get(f) || 0) + 1);
      }
      if (n.type === 'JSXAttribute' && n.value && n.value.type === 'JSXExpressionContainer') {
        const g = fieldOfMember(n.value.expression);
        if (g) asText.set(g, (asText.get(g) || 0) - 1);            // an attribute value is not text
      }
      return true;
    });
  }
  return [...uses].filter(([f, n]) => asText.get(f) === n).map(([f]) => f);
}

/** Candidate list schema: which item field feeds which role, in JSX order. */
function listFields(code, roots, bind) {
  const fields = [];
  const seen = new Set();
  const push = (f) => { if (!seen.has(f.field + ':' + f.role)) { seen.add(f.field + ':' + f.role); fields.push(f); } };
  for (const r of roots) {
    walk(r, (n) => {
      if (n.type === 'JSXElement') {
        const name = jsxName(n.openingElement.name);
        for (const a of n.openingElement.attributes) {
          if (a.type !== 'JSXAttribute' || !a.value || a.value.type !== 'JSXExpressionContainer') continue;
          const f = fieldOf(a.value.expression, bind);
          if (f == null) continue;
          const an = a.name.name;
          if (an === 'href' || an === 'to') push({ field: f, role: 'href' });
          else if (an === 'src' && /^(img|Image)$/.test(name)) push({ field: f, role: 'image' });
          else if (an === 'alt') push({ field: f, role: 'imageAlt' });
        }
        if (isBlockEl(name) || COMPOUND.test(name)) {
          const host = textHost(n, true);
          const exprs = (host.children || []).filter((c) => c.type === 'JSXExpressionContainer' && c.expression.type !== 'JSXEmptyExpression');
          if (exprs.length === 1) {
            const f = fieldOf(exprs[0].expression, bind);
            if (f != null) push({ field: f, role: roleOf(name) });
          }
        } else if (/^(span|div|strong|small|b|em|sup|sub)$/.test(name)) {
          // a price or period in a plain span (`<span>{plan.price}</span>`): content too, its role told by the demo value
          const kids = (n.children || []).filter((c) => !(c.type === 'JSXText' && !c.value.trim()));
          if (kids.length === 1 && kids[0].type === 'JSXExpressionContainer') {
            const f = fieldOf(kids[0].expression, bind);
            // (a field already used as an image's alt is still shown here: `<span>{member.name}</span>`)
            if (f != null && !fields.some((x) => x.field === f && !['imageAlt', 'image', 'href'].includes(x.role))) push({ field: f, role: 'text', loose: true });
          }
        }
      }
      if (n.type === 'JSXExpressionContainer') {
        const mc = mapCall(n.expression);
        if (mc && mc.object.type === 'MemberExpression') {
          const f = fieldOf(mc.object, bind);
          if (f != null) push({ field: f, role: 'bullets' });
          return false;
        }
      }
      return true;
    });
  }
  return fields;
}

/** Repeated sibling elements that each hold >= 2 content units (tier cards, feature cards, FAQ rows). */
function siblingGroups(root, units) {
  const groups = [];
  walk(root, (n) => {
    if (n.type !== 'JSXElement') return true;
    const kids = (n.children || []).filter((c) => c.type === 'JSXElement');
    if (kids.length < 2) return true;
    const byTag = new Map();
    for (const k of kids) {
      const t = jsxName(k.openingElement.name);
      if (!byTag.has(t)) byTag.set(t, []);
      byTag.get(t).push(k);
    }
    for (const members of byTag.values()) {
      if (members.length < 2) continue;
      const per = members.map((m) => units.filter((u) => u.el.start >= m.start && u.el.end <= m.end));
      if (per.filter((p) => p.length >= 2).length >= 2) {
        const total = per.reduce((a, p) => a + p.length, 0);
        const lens = per.map((p) => p.length), lo = Math.min(...lens), hi = Math.max(...lens);
        // a list is BALANCED: cards of similar weight — not "a heading block + everything else".
        // UNIFORM = true repeated cards (a "popular" badge may add one unit); a row of rows is not.
        const roles = [...new Set(per.flat().map((u) => u.role))].sort().join(',');
        groups.push({ members, per, total, balance: lo * members.length, uniform: lo >= 1 && hi - lo <= Math.max(1, Math.floor(hi / 4)), roles });
      }
    }
    return true;
  });
  groups.sort((a, b) => b.uniform - a.uniform || b.balance - a.balance || b.total - a.total || a.members[0].start - b.members[0].start);
  return groups;
}

/** The primary card group plus its twins: same card shape, disjoint (a 2-up row above a 4-up row). */
function cardGroups(root, units) {
  const all = siblingGroups(root, units);
  if (!all.length) return [];
  const first = all[0];
  const chosen = [first];
  const span = (g) => [g.members[0].start, g.members[g.members.length - 1].end];
  const apart = (a, b) => { const [s1, e1] = span(a), [s2, e2] = span(b); return e1 <= s2 || e2 <= s1; };
  if (first.uniform) {
    for (const g of all.slice(1)) {
      if (g.uniform && g.roles === first.roles && chosen.every((c) => apart(c, g))) chosen.push(g);
    }
  }
  return chosen.sort((a, b) => a.members[0].start - b.members[0].start);
}

const attrValueSrc = (code, a, inner = null) => {
  if (!a || !a.value) return null;
  if (a.value.type === 'StringLiteral') return JSON.stringify(a.value.value);
  if (a.value.type === 'JSXExpressionContainer') {
    // an expression moves with the owner's words to the variant's call site — only when every name it uses is
    // defined OUTSIDE the clicked element (`tel:${c.phone}` with a module-level `c`), never a name bound inside it
    if (inner && usesAny(a.value.expression, inner)) return null;
    return code.slice(a.value.expression.start, a.value.expression.end);
  }
  return null;
};

/** Names bound inside an element (function params, declarations): not in scope at the element's own position. */
function innerBindings(el) {
  const names = new Set();
  const bind = (pat) => {
    if (!pat) return;
    if (pat.type === 'Identifier') names.add(pat.name);
    else if (pat.type === 'ObjectPattern') pat.properties.forEach((pr) => bind(pr.type === 'RestElement' ? pr.argument : pr.value));
    else if (pat.type === 'ArrayPattern') pat.elements.forEach(bind);
    else if (pat.type === 'AssignmentPattern') bind(pat.left);
    else if (pat.type === 'RestElement') bind(pat.argument);
  };
  walk(el, (n) => {
    if (/Function/.test(n.type) && Array.isArray(n.params)) n.params.forEach(bind);
    if (n.type === 'VariableDeclarator') bind(n.id);
    if (n.type === 'CatchClause') bind(n.param);
    return true;
  });
  return names;
}

/** Does an expression read any of these names (object keys and non-computed members excluded)? */
function usesAny(expr, names) {
  if (!names.size) return false;
  let hit = false;
  walk(expr, (n, parent) => {
    if (hit) return false;
    if (n.type === 'Identifier' && names.has(n.name)
      && !(parent && parent.type === 'MemberExpression' && parent.property === n && !parent.computed)
      && !(parent && (parent.type === 'ObjectProperty') && parent.key === n && !parent.computed)) hit = true;
    return !hit;
  });
  return hit;
}

/**
 * A list item's text as a JS value. Plain text stays a string; the owner's `{c.phone}` becomes `c.phone` and
 * `Cleaning in {c.city}.` a template literal — never the literal text "{c.phone}". Names bound inside the clicked
 * element are out of scope at the call site: then only the plain text is kept.
 */
function unitValue(u, inner) {
  if (!u.dynamic) return u.text;
  let frag;
  try { frag = parse('v.tsx', `const __v = <>${u.src}</>;`).program.body[0].declarations[0].init; } catch { return u.text; }
  const kids = frag.children.filter((k) => !(k.type === 'JSXText' && !k.value.trim()));
  if (!kids.every((k) => k.type === 'JSXText' || (k.type === 'JSXExpressionContainer' && k.expression.type !== 'JSXEmptyExpression'
    && !/^JSX/.test(k.expression.type)))) return u.text;
  if (inner && kids.some((k) => k.type === 'JSXExpressionContainer' && usesAny(k.expression, inner))) return u.text;
  const src = `const __v = <>${u.src}</>;`;
  if (kids.length === 1 && kids[0].type === 'JSXExpressionContainer') {
    const e = kids[0].expression;
    return { __src: src.slice(e.start, e.end) };
  }
  const parts = kids.map((k) => (k.type === 'JSXText' ? k.value.replace(/\s+/g, ' ').replace(/[`\\]/g, '\\$&').replace(/\$\{/g, '\\${')
    : '${' + src.slice(k.expression.start, k.expression.end) + '}'));
  return { __src: '`' + parts.join('').trim() + '`' };
}

/**
 * A card's words into a card's slots. A role both sides have pairs exactly (the title to the title — never the date
 * line); when the owner wrote more body text than the card holds, its longest text wins (the excerpt, not the
 * "12 Sep · Guides" line); the rest pairs in document order (a tier name may be an h3 on one side, a span on the other).
 */
function pairCard(o, sl) {
  const pairs = [], oLeft = [...o], sLeft = [...sl];
  let exact = false;
  for (const r of ['figure', 'heading', 'quote', 'label']) {
    const oo = oLeft.filter((u) => u.role === r), ss = sLeft.filter((x) => x.role === r);
    for (let k = 0; k < Math.min(oo.length, ss.length); k++) {
      pairs.push([oo[k], ss[k]]); oLeft.splice(oLeft.indexOf(oo[k]), 1); sLeft.splice(sLeft.indexOf(ss[k]), 1); exact = true;
    }
  }
  const left = [];
  const ot = oLeft.filter((u) => u.role === 'text'), st = sLeft.filter((x) => x.role === 'text');
  if (exact && st.length && ot.length > sLeft.length) {
    const keep = new Set([...ot].sort((a, b) => b.text.length - a.text.length).slice(0, sLeft.length));
    for (const u of ot) if (!keep.has(u)) { left.push(u); oLeft.splice(oLeft.indexOf(u), 1); }
  }
  const n = Math.min(oLeft.length, sLeft.length);
  for (let k = 0; k < n; k++) pairs.push([oLeft[k], sLeft[k]]);
  return { pairs, left: left.concat(oLeft.slice(n)), empty: sLeft.slice(n) };
}

/** A value for a generated list item: string data, or JS source kept verbatim (an owner's link expression). */
const itemValue = (v) => (v && typeof v === 'object' && typeof v.__src === 'string' ? v.__src : JSON.stringify(v));
const listSrc = (items) => '[' + items.map((o) => '{ ' + Object.entries(o).map(([k, v]) => `${JSON.stringify(k)}: ${itemValue(v)}`).join(', ') + ' }').join(', ') + ']';

/**
 * The owner's logo row: 2+ images side by side (one parent, or one grandparent when each has its own box) — or a
 * data list whose items are an image and at most a name. [] when there is none.
 */
export function ownerLogos(orig) {
  const rows = new Map();
  for (const im of orig.images || []) if (im.src && im.row != null) { if (!rows.has(im.row)) rows.set(im.row, []); rows.get(im.row).push(im); }
  const best = [...rows.values()].sort((a, b) => b.length - a.length)[0] || [];
  if (best.length >= 2) return best;
  for (const l of orig.lists || []) {
    const its = l.items.filter((it) => it.images.length === 1 && it.images[0].src && it.units.length <= 1);
    if (its.length >= 2 && its.length === l.items.length) return its.map((it) => it.images[0]);
  }
  return [];
}

/** Content of the clicked element. `ast` = the whole file (to evaluate literal data arrays). */
export function extractUnits(code, el, ast = null) {
  const fileAst = ast || parse('x.tsx', code);
  const c = collect(code, el, fileAst, 'original');
  const inner = innerBindings(el);
  // one template, one role: the spot that shows "€290" in one plan shows "Custom" in another — both are the price
  for (const l of c.lists) {
    const priced = new Set();
    for (const it of l.items) for (const u of it.units) if (u.role === 'price' && u.tpl) priced.add(u.tpl);
    for (const it of l.items) for (const u of it.units) if (u.role === 'text' && u.tpl && priced.has(u.tpl)) u.role = 'price';
    const figured = new Set();
    for (const it of l.items) for (const u of it.units) if (u.role === 'figure' && u.tpl) figured.add(u.tpl);
    for (const it of l.items) for (const u of it.units) if (u.role === 'text' && u.tpl && figured.has(u.tpl)) u.role = 'figure';
  }
  const pub = (u) => ({
    role: u.role, sub: u.sub || null, level: u.level, text: u.text, src: u.src.trim(), dynamic: !!u.dynamic, tag: u.tag || null,
    href: u.href !== undefined ? u.href : attrValueSrc(code, u.hrefAttr, inner), list: u.list ? c.lists.indexOf(u.list) : null, item: u.itemIdx ?? null,
  });
  const lists = c.lists.map((l) => ({ items: l.items.map((it) => ({ units: it.units.map(pub), images: it.images, bullets: it.bullets })) }));
  let units = c.units.map(pub);
  if (!lists.length) {
    // the owner's cards, twin rows concatenated in reading order (2-up + 4-up = one list of 6)
    const per = cardGroups(el, c.units).flatMap((g) => g.per);
    if (per.length >= 2) {
      const idx = new Map();
      per.forEach((p, i) => p.forEach((u) => idx.set(u, i)));
      units = c.units.map((u) => ({ ...pub(u), list: idx.has(u) ? 0 : null, item: idx.has(u) ? idx.get(u) : null }));
      lists.push({ literal: true, items: per.map((p) => ({ units: p.map((u) => ({ ...pub(u), list: 0 })), images: [], bullets: [] })) });
    }
  }
  // a unit whose JSX reads a name bound inside the element cannot move to the call site: carry its text instead
  const safe = (u) => {
    if (!u.dynamic || !inner.size) return u;
    let bad = false;
    try { walk(parse('v.tsx', `const __v = <>${u.src}</>;`), (n) => { if (n.type === 'JSXExpressionContainer' && usesAny(n.expression, inner)) bad = true; return !bad; }); } catch { bad = true; }
    return bad ? { ...u, src: u.text.replace(/[{}<>]/g, ''), dynamic: false } : u;
  };
  units = units.map(safe);
  for (const l of lists) for (const it of l.items) it.units = it.units.map(safe);
  // the owner's own <form> (its action, handlers, field names): it moves whole into a design's form spot
  const forms = [];
  walk(el, (n) => {
    if (n.type !== 'JSXElement') return true;
    if (jsxName(n.openingElement.name) !== 'form') return true;
    const own = innerBindings(n);
    const outside = new Set([...inner].filter((x) => !own.has(x)));
    forms.push({ src: usesAny(n, outside) ? null : code.slice(n.start, n.end), start: n.start, end: n.end });
    return false;
  });
  if (forms.length) {
    const fi = (u) => forms.findIndex((f) => u.el.start >= f.start && u.el.end <= f.end);
    units = units.map((u, i) => { const k = fi(c.units[i]); return k >= 0 ? { ...u, form: k } : u; });
  }
  return {
    forms: forms.map((f) => ({ src: f.src })),
    units,
    inner,
    images: c.images.map((i) => {
      // images side by side (a logo row): the same parent, or the same grandparent when each sits in its own box
      const perParent = c.images.filter((j) => j.parent === i.parent).length;
      const row = perParent >= 2 ? i.parent : i.grand;
      const jsx = code.slice(i.el.start, i.el.end);
      return { src: attrValueSrc(code, i.src, inner), alt: attrValueSrc(code, i.alt, inner), row: row ? row.start : null, jsx: usesAny(i.el, inner) ? null : jsx };
    }),
    inputs: c.inputs.map((i) => ({ placeholder: attrValueSrc(code, i.ph), form: forms.findIndex((f) => i.el.start >= f.start && i.el.end <= f.end) })),
    lists,
    dynamicLists: c.dynamicLists,
  };
}

/* ------------------------------------------------------------------ candidate */

function findComponentFn(ast, exp) {
  const byName = {};
  for (const st of ast.program.body) {
    const d = st.type === 'ExportNamedDeclaration' || st.type === 'ExportDefaultDeclaration' ? st.declaration : st;
    if (!d) continue;
    if (d.type === 'FunctionDeclaration' && d.id) byName[d.id.name] = d;
    if (d.type === 'VariableDeclaration') for (const v of d.declarations) {
      if (!v.id.name || !v.init) continue;
      if (/Function/.test(v.init.type)) byName[v.id.name] = v.init;
      else if (v.init.type === 'CallExpression' && v.init.arguments[0] && /Function/.test(v.init.arguments[0].type)) byName[v.id.name] = v.init.arguments[0];
    }
  }
  if (exp.kind === 'default') {
    const st = ast.program.body.find((s) => s.type === 'ExportDefaultDeclaration');
    if (!st) return null;
    const d = st.declaration;
    if (/Function/.test(d.type)) return d;
    if (d.type === 'Identifier') return byName[d.name] || null;
    if (d.type === 'CallExpression' && d.arguments[0] && /Function/.test(d.arguments[0].type)) return d.arguments[0];
    return null;
  }
  return byName[exp.name] || null;
}

function returnedJsx(fn) {
  const out = [];
  if (fn.body.type !== 'BlockStatement') {
    walk(fn.body, (n) => { if (n.type === 'JSXElement' || n.type === 'JSXFragment') { out.push(n); return false; } return true; });
    return out;
  }
  walk(fn.body, (n) => {
    if (n !== fn.body && /Function/.test(n.type)) return false;
    if (n.type === 'ReturnStatement' && n.argument) {
      walk(n.argument, (m) => { if (m.type === 'JSXElement' || m.type === 'JSXFragment') { out.push(m); return false; } return true; });
      return false;
    }
    return true;
  });
  return out;
}

const CHROME = /(^|\.)(\w*Header|\w*Navbar|\w*NavBar|\w*Nav)$/;

/** The text-rendered prop defaults of a design's exported component (see defaultPropSlots), for callers outside. */
export function defaultPropsOf(file, code, exp) {
  let ast;
  try { ast = parse(file, code); } catch { return []; }
  const fn = exp ? findComponentFn(ast, exp) : null;
  return fn ? defaultPropSlots(fn) : [];
}

/**
 * A component whose words are its props' defaults — `function CardFlip({ title = "Design Systems", features = [...] })`
 * rendering `<h3>{title}</h3>`: each such prop is a slot, filled by passing the prop itself (key `@title`).
 */
function defaultPropSlots(fn) {
  const p0 = fn.params[0];
  const pat = p0 && (p0.type === 'ObjectPattern' ? p0 : p0.type === 'AssignmentPattern' && p0.left.type === 'ObjectPattern' ? p0.left : null);
  if (!pat) return [];
  const out = [];
  const up = new Map();
  walk(fn.body, (n, parent) => { if (n.type === 'JSXElement') up.set(n, parent); return true; });
  const propNames = new Set(pat.properties.filter((pr) => pr.type === 'ObjectProperty').map((pr) => (pr.value.type === 'AssignmentPattern' ? pr.value.left.name : pr.value.name)));
  // the link a button prop sits in (`<a href={primaryCtaUrl}>{primaryCtaText}</a>`): the owner's href goes there
  const hrefPropOf = (el) => {
    for (let e = el, i = 0; e && e.type === 'JSXElement' && i < 3; e = up.get(e), i++) {
      const h = attr(e, 'href') || attr(e, 'to');
      if (h && h.value && h.value.type === 'JSXExpressionContainer' && h.value.expression.type === 'Identifier' && propNames.has(h.value.expression.name)) return h.value.expression.name;
    }
    return null;
  };
  for (const pr of pat.properties) {
    if (pr.type !== 'ObjectProperty' || pr.value.type !== 'AssignmentPattern' || pr.value.left.type !== 'Identifier') continue;
    const name = pr.value.left.name, d = pr.value.right;
    const str = d.type === 'StringLiteral' ? d.value : d.type === 'TemplateLiteral' && !d.expressions.length ? d.quasis[0].value.cooked : null;
    const strs = d.type === 'ArrayExpression' && d.elements.length && d.elements.every((e) => e && e.type === 'StringLiteral') ? d.elements.map((e) => e.value) : null;
    if (str == null && !strs) continue;
    let host = null, mapped = false;
    walk(fn.body, (n, parent) => {
      if (host || mapped) return false;
      // `{title}`, or a fallback after what is passed in (`{children || subtitle}`)
      const e = n.type === 'JSXExpressionContainer' ? n.expression : null;
      const shown = e && ((e.type === 'Identifier' && e.name === name) || (e.type === 'LogicalExpression' && /^(\|\||\?\?)$/.test(e.operator) && e.right.type === 'Identifier' && e.right.name === name));
      if (str != null && shown && parent && parent.type === 'JSXElement') { host = parent; return false; }
      if (strs && mapCall(n) && mapCall(n).object.type === 'Identifier' && mapCall(n).object.name === name) { mapped = true; return false; }
      return true;
    });
    if (str != null && host && /[\p{L}]/u.test(str)) {
      const tag = jsxName(host.openingElement.name), lv = /^h([1-6])$/.exec(tag);
      const role = roleOf(tag) === 'action' ? 'action' : roleOf(tag);
      const hrefProp = role === 'action' ? hrefPropOf(host) : null;
      out.push({ key: '@' + name, role: isFigure(str) ? 'figure' : role, sub: role === 'action' ? 'cta' : null, level: lv ? Number(lv[1]) : null, demo: str, propName: name, at: host.start, ...(hrefProp ? { hrefProp } : {}) });
    } else if (strs && mapped) out.push({ key: '@' + name, role: 'bullets', demo: `${strs.length} demo bullets`, propName: name });
  }
  return out;
}

/**
 * Parameterize the candidate entry file -> { code, slots[], lists[], prop, removed[] }.
 * opts.stripChrome: drop header/navbar components a block embeds (the site has its own) and
 * turn a nested <main> into a <div>.
 */
export function parameterize(file, code, exp, opts = {}) {
  const ast = parse(file, code);
  const fn = exp ? findComponentFn(ast, exp) : null;
  if (!fn) return { code, slots: [], lists: [], reason: 'NO_COMPONENT_FUNCTION' };
  const roots = returnedJsx(fn);
  const prop = /\bcontent\b/.test(code) ? 'dhContent' : 'content';
  const tsFile = /\.tsx?$/.test(file);
  const edits = [];
  const slots = [];
  const counters = {};
  const key = (role) => { counters[role] = (counters[role] || 0) + 1; return role + counters[role]; };

  const p0 = fn.params[0];
  const typeLit = `{ ${prop}?: Record<string, any> }`;
  let acc;
  if (!p0) {
    const open = code.indexOf('(', fn.id ? fn.id.end : (fn.typeParameters ? fn.typeParameters.end : fn.start));
    edits.push({ start: open + 1, end: open + 1, text: tsFile ? `{ ${prop} = {} }: ${typeLit} = {}` : `{ ${prop} = {} } = {}` });
    acc = (k) => `${prop}.${k}`;
  } else if (p0.type === 'ObjectPattern' || (p0.type === 'AssignmentPattern' && p0.left.type === 'ObjectPattern')) {
    const pat = p0.type === 'ObjectPattern' ? p0 : p0.left;
    edits.push({ start: pat.start + 1, end: pat.start + 1, text: ` ${prop} = {},` });
    if (pat.typeAnnotation && tsFile) edits.push({ start: pat.typeAnnotation.end, end: pat.typeAnnotation.end, text: ` & ${typeLit}` });
    acc = (k) => `${prop}.${k}`;
  } else if (p0.type === 'Identifier') {
    if (p0.typeAnnotation && tsFile) edits.push({ start: p0.typeAnnotation.end, end: p0.typeAnnotation.end, text: ` & ${typeLit}` });
    acc = (k) => `${p0.name}.${prop}?.${k}`;
  } else {
    return { code, slots: [], lists: [], reason: 'UNSUPPORTED_SIGNATURE' };
  }
  const propSlots = defaultPropSlots(fn);

  const removed = [];
  const lists = [];
  const groups = [];
  const logoRows = [];
  const logoSwaps = [];
  const forms = [];
  const formSwaps = [];
  const conds = new Map();
  const cut = [];
  for (const root of roots) {
    if (opts.stripChrome) {
      walk(root, (n) => {
        if (n.type !== 'JSXElement') return true;
        const nm = jsxName(n.openingElement.name);
        if (/^[A-Z]/.test(nm) && CHROME.test(nm)) { cut.push({ start: n.start, end: n.end }); removed.push(nm); return false; }
        if (nm === 'main') {
          edits.push({ start: n.openingElement.name.start, end: n.openingElement.name.end, text: 'div' });
          if (n.closingElement) edits.push({ start: n.closingElement.name.start, end: n.closingElement.name.end, text: 'div' });
        }
        return true;
      });
    }
    const c = collect(code, root, ast, 'candidate');
    const inCut = (node) => cut.some((x) => x.start <= node.start && node.end <= x.end);
    const parents = new Map();
    walk(root, (n, parent) => { if (n.type === 'JSXElement') parents.set(n, parent); return true; });
    // a label that switches with a state (`{hovered ? "Attracting" : "Hover me"}`): one slot, the owner's words in
    // both states (list templates and attribute values excepted)
    const choices = [];
    walk(root, (n, parent) => {
      if (n.type === 'JSXAttribute' || mapCall(n)) return false;
      if (n.type === 'JSXExpressionContainer' && parent && parent.type === 'JSXElement' && n.expression.type === 'ConditionalExpression'
        && [n.expression.consequent, n.expression.alternate].every((e) => isStaticExpr(e) && /\p{L}/u.test(e.value ?? e.quasis[0].value.cooked))) {
        let act = false;
        for (let p = parent; p && p.type === 'JSXElement'; p = parents.get(p)) if (roleOf(jsxName(p.openingElement.name)) === 'action') { act = true; break; }
        const alt = n.expression.alternate;
        choices.push({ node: n, role: act ? 'action' : 'text', demo: alt.value ?? alt.quasis[0].value.cooked });
        return false;
      }
      return true;
    });
    const inChildren = (n) => { const p = parents.get(n); return p && (p.type === 'JSXElement' || p.type === 'JSXFragment') && (p.children || []).includes(n); };
    // one wrapper per element, conditions AND-ed: `{a !== false && b === true && (<el/>)}`
    const addCond = (node, cond) => { if (!conds.has(node)) conds.set(node, []); conds.get(node).push(cond); };
    // 1. third-party brand logos (a registry's demo "trusted by" row) are hidden unless asked for
    if (opts.logoLocals && opts.logoLocals.length) {
      const rows = new Set();
      const logos = [];
      walk(root, (n) => {
        if (n.type === 'JSXElement' && opts.logoLocals.includes(jsxName(n.openingElement.name))) { logos.push(n); return false; }
        return true;
      });
      const chain = (n) => { const ch = []; for (let p = parents.get(n); p; p = parents.get(p)) if (p.type === 'JSXElement') ch.unshift(p); return ch; };
      // the words an element shows besides the logos (a "Trusted by" label is short; a testimonial card is not)
      const textLen = (n) => {
        let t = 0;
        walk(n, (m) => {
          if (m.type === 'JSXElement' && opts.logoLocals.includes(jsxName(m.openingElement.name))) return false;
          if (m.type === 'JSXText') t += m.value.trim().length;
          else if (m.type === 'StringLiteral' || (m.type === 'TemplateLiteral' && !m.expressions.length)) t += m.type === 'StringLiteral' ? m.value.length : m.quasis[0].value.raw.length;
          return m.type !== 'JSXAttribute';
        });
        return t;
      };
      const swaps = [];
      if (logos.length) {
        // the lowest common ancestor of every logo = the row; plus its label when the row's parent
        // holds only label + row
        const chains = logos.map(chain);
        let lca = null;
        for (let i = 0; i < chains[0].length; i++) { if (chains.every((ch) => ch[i] === chains[0][i])) lca = chains[0][i]; else break; }
        // the owner has a logo row of their own: it takes the place of the design's demo brands, same row, same spacing
        if (opts.logoSwap && logos.length >= 2 && lca && inChildren(lca) && textLen(lca) <= 60 && (lca.children || []).some((x) => x.type === 'JSXElement')) swaps.push(lca);
        else if (lca && lca !== root && textLen(lca) > 60) {
          // logos inside real content (a company mark on each testimonial card): each logo goes, the content stays
          for (const lg of logos) {
            let box = lg;
            for (let p = parents.get(box); p && p.type === 'JSXElement' && p !== root && textLen(p) === 0; p = parents.get(p)) box = p;
            rows.add(box);
          }
        } else if (lca && lca !== root) {
          const up = parents.get(lca);
          const sib = up && up.type === 'JSXElement' ? (up.children || []).filter((x) => x.type === 'JSXElement') : [];
          // the row's label goes with it ("Trusted by" + logos); a card whose illustration holds logos keeps its words
          const labelOnly = sib.every((x) => x === lca || textLen(x) <= 40);
          rows.add(sib.length <= 2 && labelOnly && up !== root && inChildren(up) ? up : lca);
        } else {
          for (const lg of logos) { const p = chain(lg).pop(); if (p && p !== root) rows.add(p); }
        }
      }
      for (const r of rows) {
        if (!inChildren(r) || inCut(r)) continue;
        const k = 'logos' + (logoRows.length + 1);
        addCond(r, `${acc(k + 'Show')} === true`);
        logoRows.push(k);
        cut.push({ start: r.start + 0.5, end: r.end - 0.5, hidden: true });
      }
      for (const r of swaps) {
        if (inCut(r)) continue;
        const k = 'logoRow' + (logoSwaps.length + 1);
        const kids = (r.children || []).filter((x) => !(x.type === 'JSXText' && !x.value.trim()));
        const a = kids[0].start, b = kids[kids.length - 1].end;
        edits.push({ start: a, end: b, text: `{${acc(k)} ?? (<>${code.slice(a, b)}</>)}`, keep: true });
        // the owner may have more logos than the design's row: a flex row wraps instead of running off a phone
        const ca = attr(r, 'className');
        if (ca && ca.value && ca.value.type === 'StringLiteral' && /(^|\s)flex(\s|$)/.test(ca.value.value) && !/flex-(wrap|nowrap|col)|overflow-/.test(ca.value.value)) {
          edits.push({ start: ca.value.start, end: ca.value.end, text: JSON.stringify(ca.value.value + ' flex-wrap'), keep: true });
        }
        // the design's demo brands never show under the owner's name: theirs, or the row is empty
        logoSwaps.push(k);
        cut.push({ start: r.start + 0.5, end: r.end - 0.5, hidden: true });
      }
    }
    // 1b. a design's own form (newsletter, "enter your email") posts nowhere: hidden unless the owner's
    //     section has one or the slot IS a form page (contact, login) — no dead-end UI by default
    // …and when the owner's section has a form of its own, theirs takes the design form's place (their fields,
    //     their action) — never a "Company size" select nobody reads
    if (opts.forms === 'swap') {
      walk(root, (n) => {
        if (n.type !== 'JSXElement') return true;
        if (jsxName(n.openingElement.name) !== 'form') return true;
        if (n !== root && inChildren(n) && !inCut(n)) {
          const k = 'form' + (formSwaps.length + forms.length + 1);
          if (!formSwaps.length) { edits.push({ start: n.start, end: n.end, text: `{${acc(k)} ?? (${code.slice(n.start, n.end)})}`, keep: true }); formSwaps.push(k); }
          else { addCond(n, `${acc(k + 'Show')} === true`); forms.push(k); }
          cut.push({ start: n.start + 0.5, end: n.end - 0.5, hidden: true });
        }
        return false;
      });
    }
    if (opts.forms === 'hide') {
      walk(root, (n) => {
        if (n.type !== 'JSXElement') return true;
        if (jsxName(n.openingElement.name) !== 'form') return true;
        if (n !== root && inChildren(n) && !inCut(n)) {
          const k = 'form' + (forms.length + 1);
          addCond(n, `${acc(k + 'Show')} === true`);
          forms.push(k);
          cut.push({ start: n.start + 0.5, end: n.end - 0.5, hidden: true });
        }
        return false;
      });
    }
    // 2. repeated cards (tiers, features) — the owner's items fill them in order; extras hide
    const gs = groups.length ? [] : cardGroups(root, c.units.filter((u) => !inCut(u.el)));
    const memberOf = new Map();
    const gnodes = [];
    for (const g of gs) {
      const gk = 'group' + (groups.length + 1);
      g.per.forEach((p, i) => p.forEach((u) => memberOf.set(u, { gk, i })));
      g.members.forEach((m, i) => { if (inChildren(m)) addCond(m, `${acc(gk + 'Show' + (i + 1))} !== false`); });
      // hiding cards must not leave empty grid columns: the container gets one full class list per count
      const box = parents.get(g.members[0]);
      const ca = box && box.type === 'JSXElement' ? attr(box, 'className') : null;
      const N = g.members.length;
      let cols = false;
      if (ca && ca.value && ca.value.type === 'StringLiteral' && new RegExp(`grid-cols-${N}\\b`).test(ca.value.value)) {
        const v = ca.value.value;
        const variant = (n) => JSON.stringify(v.replace(new RegExp(`grid-cols-${N}\\b`, 'g'), `grid-cols-${n}`));
        let expr = JSON.stringify(v);
        for (let n = N - 1; n >= 1; n--) expr = `${acc(gk + 'Cols')} === ${n} ? ${variant(n)} : ${expr}`;
        edits.push({ start: ca.value.start, end: ca.value.end, text: `{${expr}}` });
        cols = true;
      }
      // with twin rows, a row the owner's items do not reach disappears whole (no empty bordered box)
      let boxShow = false;
      if (gs.length > 1 && box && box !== root && box.type === 'JSXElement' && inChildren(box)) { addCond(box, `${acc(gk + 'BoxShow')} !== false`); boxShow = true; }
      groups.push({ key: gk, count: N, cols, ...(boxShow ? { box: true } : {}) });
      gnodes.push([gk, g]);
    }
    // a featured card's extra line (its "Popular" badge): a unit none of its sibling cards has. It takes the owner's
    // words only when they have one more, else it goes whole — never the product name in the badge, every word shifted
    const extra = new Set();
    const sigOf = (u) => { const a = attr(u.el, 'className'); return u.role + '|' + u.tag + '|' + (a && a.value && a.value.type === 'StringLiteral' ? a.value.value : ''); };
    for (const [, g] of gnodes) {
      const lo = Math.min(...g.per.map((p) => p.length));
      if (!g.uniform || lo < 2) continue;
      g.per.forEach((p, i) => {
        if (p.length !== lo + 1) return;
        const others = new Set(g.per.filter((_, j) => j !== i).flat().map(sigOf));
        for (const u of p) if (!others.has(sigOf(u))) extra.add(u);
      });
    }
    for (const u of c.units) {
      if (inCut(u.el)) continue;
      const k = key(u.role);
      if (extra.has(u)) { u.optional = true; if (inChildren(u.el)) addCond(u.el, `${acc(k)} !== false`); }
      const inSentence = (node) => { const p = parents.get(node); return !!(p && (p.children || []).some((c) => c.type === 'JSXText' && c.value.trim())); };
      if (u.role === 'action' && u.outer && inChildren(u.outer) && !u.outer.__dhWrapped && !inSentence(u.outer)) {
        u.outer.__dhWrapped = true;
        addCond(u.outer, `${acc(k + 'Show')} !== false`);
      }
      edits.push({ start: u.childrenStart, end: u.childrenEnd, text: `{${acc(k)} ?? <span data-dh-demo="">${code.slice(u.childrenStart, u.childrenEnd)}</span>}` });
      const slot = { key: k, role: u.role, sub: u.sub || null, level: u.level, demo: u.text, at: u.childrenStart, hideable: u.role === 'action' && !!(u.outer && u.outer.__dhWrapped), ...(u.optional ? { optional: true } : {}) };
      if (memberOf.has(u)) { slot.group = memberOf.get(u).gk; slot.member = memberOf.get(u).i; }
      const hv = u.hrefAttr && u.hrefAttr.value;
      if (u.role === 'action' && hv && hv.type === 'StringLiteral') {
        edits.push({ start: hv.start, end: hv.end, text: `{${acc(k + 'Href')} ?? ${JSON.stringify(hv.value)}}` });
        slot.href = true;
      }
      slots.push(slot);
    }
    for (const ch of choices) {
      if (inCut(ch.node)) continue;
      const k = key(ch.role);
      edits.push({ start: ch.node.start, end: ch.node.end, text: `{${acc(k)} ?? <span data-dh-demo="">${code.slice(ch.node.start, ch.node.end)}</span>}` });
      slots.push({ key: k, role: ch.role, sub: ch.role === 'action' ? 'cta' : null, level: null, demo: ch.demo, at: ch.node.start });
    }
    for (const im of c.images) {
      if (inCut(im.el)) continue;
      const k = key('image');
      const sv = im.src.value;
      if (sv.type !== 'StringLiteral') continue;
      edits.push({ start: sv.start, end: sv.end, text: `{${acc(k)} ?? ${JSON.stringify(sv.value)}}` });
      if (im.alt && im.alt.value && im.alt.value.type === 'StringLiteral') edits.push({ start: im.alt.value.start, end: im.alt.value.end, text: `{${acc(k + 'Alt')} ?? ${JSON.stringify(im.alt.value.value)}}` });
      slots.push({ key: k, role: 'image', demo: sv.value, localDemo: /^(\/|https?:)/.test(sv.value) });
    }
    for (const inp of c.inputs) {
      if (inCut(inp.el) || inp.ph.value.type !== 'StringLiteral') continue;
      const k = key('placeholder');
      edits.push({ start: inp.ph.value.start, end: inp.ph.value.end, text: `{${acc(k)} ?? ${JSON.stringify(inp.ph.value.value)}}` });
      slots.push({ key: k, role: 'placeholder', demo: inp.ph.value.value });
    }
    for (const b of c.bullets) {
      if (inCut(b.node)) continue;
      const k = key('bullets');
      edits.push({ start: b.node.start, end: b.node.end, text: tsFile ? `((${acc(k)} ?? ${code.slice(b.node.start, b.node.end)}) as string[])` : `(${acc(k)} ?? ${code.slice(b.node.start, b.node.end)})` });
      const slot = { key: k, role: 'bullets', demo: `${b.count} demo bullets` };
      for (const [gk, g] of gnodes) { const mi = g.members.findIndex((m) => m.start <= b.node.start && b.node.end <= m.end); if (mi >= 0) { slot.group = gk; slot.member = mi; break; } }
      slots.push(slot);
    }
    for (const l of c.lists) {
      if (inCut(l.object) || !l.fields.some((f) => CONTENT_ROLES.includes(f.role))) continue;
      const k = key('list');
      const a = acc(k);
      const merge = tsFile ? `${a}.map((o: any, i: number) => ({ ...${l.name}[i % ${l.name}.length], ...o }))` : `${a}.map((o, i) => ({ ...${l.name}[i % ${l.name}.length], ...o }))`;
      edits.push({ start: l.object.start, end: l.object.end, text: tsFile ? `((${a} ? ${merge} : ${l.name}) as typeof ${l.name})` : `(${a} ? ${merge} : ${l.name})` });
      for (const k0 of l.consts || []) edits.push({ start: k0.start, end: k0.end, text: `{(${k0.param}${tsFile ? ' as any' : ''}).dhAction ?? <span data-dh-demo="">${k0.text}</span>}` });
      lists.push({ key: k, fields: l.fields, demoCount: l.demoCount, demoItems: l.demoItems || [], textOnly: l.textOnly || [], at: l.object.start });
    }
  }
  for (const [node, cs] of conds) {
    if (cut.some((x) => !x.hidden && x.start <= node.start && node.end <= x.end)) continue;
    edits.push({ start: node.start, end: node.start, text: `{${cs.join(' && ')} && (` }, { start: node.end, end: node.end, text: ')}' });
  }
  for (const x of cut) if (!x.hidden) edits.push({ ...x, text: '' });
  const kept = edits.filter((e) => e.keep || (e.text === '' && !e.hidden) || !cut.some((x) => x.start <= e.start && e.end <= x.end));
  kept.sort((a, b) => b.start - a.start || b.end - a.end);
  let out = code;
  for (const e of kept) out = out.slice(0, e.start) + e.text + out.slice(e.end);
  if (!opts.noVerify) parse(file, out);                        // must still parse — throws otherwise (noVerify: debugging only)
  return { code: out, slots: slots.concat(propSlots), lists, groups, logoRows, logoSwaps, forms, formSwaps, prop, removed };
}

/* ------------------------------------------------------------------ binding */

/**
 * Pair original content with candidate slots -> { props: [[key, src]], carried[], dropped[], demo[] }.
 * When both sides have lists, list items travel as data; otherwise unrolled items pair flat.
 */
/**
 * A design's list of plain links (label + href) against the owner's titled columns (a heading and several links
 * each — a typical footer): the owner's links become that list, one item per link, and the column titles, brand
 * line and description become ordinary text for the design's text slots. Without this, only the first link of
 * each column reached the design (2 of 8 in a real footer) and every footer was refused as a poor fit.
 */
function adaptLinkLists(orig, candLists) {
  if (!candLists.length || !orig.lists.length) return orig;
  let changed = false;
  const loose = new Set();
  const lists = orig.lists.map((ol, li) => {
    const cl = candLists[li];
    if (!cl) return ol;
    const roles = new Set(cl.fields.map((f) => f.role));
    const label = roles.has('action') ? 'action' : roles.has('item') ? 'item' : null;
    if (!label || !roles.has('href') || ![...roles].every((r) => ['href', 'action', 'item', 'image'].includes(r))) return ol;
    const acts = ol.items.flatMap((it) => it.units.filter((u) => u.role === 'action'));
    const grouped = ol.items.some((it) => it.units.filter((u) => u.role === 'action').length > 1 || it.units.some((u) => u.role !== 'action'));
    if (!grouped || acts.length < 2) return ol;
    changed = true;
    ol.items.forEach((it) => it.units.filter((u) => u.role !== 'action').forEach((u) => loose.add(u.text + '\u0000' + u.src)));
    return { ...ol, items: acts.map((a) => ({ units: [{ ...a, role: label }], images: [], bullets: [] })) };
  });
  if (!changed) return orig;
  const units = orig.units.map((u) => (u.list !== null && u.role !== 'action' && loose.has(u.text + '\u0000' + u.src) ? { ...u, list: null, item: null } : u));
  return { ...orig, units, lists };
}

/** The words a design list shows per item, in the order it shows them (one entry per field). */
const cellFields = (cl) => cl.fields.filter((f, i) => ['text', 'price', 'figure', 'item', 'heading', 'label', 'quote'].includes(f.role)
  && cl.fields.findIndex((g) => g.field === f.field && g.role !== 'imageAlt' && g.role !== 'href' && g.role !== 'image') === i);

/**
 * The owner's table: rows of plain cells, every row as wide (a feature, then one value per column), no images.
 * Its width, or 0.
 */
function matrixWidth(ol) {
  if (!ol || ol.items.length < 2) return 0;
  const k = ol.items[0].units.length;
  return k >= 3 && ol.items.every((it) => it.units.length === k && !it.images.length && !it.bullets.length && it.units.every((u) => ['text', 'figure', 'price', 'label'].includes(u.role))) ? k : 0;
}

export function bind(orig, cand, opts = {}) {
  let slots = cand.slots || cand;
  const candLists = cand.lists || [];
  orig = adaptLinkLists(orig, candLists);
  const props = [], carried = [], dropped = [], demo = [], hidden = [];
  // what a design cannot hold at all and the section cannot work without (the owner's form: a newsletter whose
  // email field vanished leaves a dead "Subscribe" link) — such a design is not offered
  let lost = null;
  if ((orig.forms || [])[0] && orig.forms[0].src && !(cand.formSwaps || []).length) lost = 'form';
  if ((cand.formSwaps || []).length && (orig.forms || [])[0] && orig.forms[0].src) {
    props.push([cand.formSwaps[0], `<>${orig.forms[0].src}</>`]);
    for (const u of orig.units.filter((x) => x.form === 0)) carried.push({ role: u.role, text: u.text });
    orig = { ...orig, units: orig.units.filter((x) => x.form !== 0), inputs: (orig.inputs || []).filter((x) => x.form !== 0) };
  }
  // a comparison table goes into a design's table — row by row, cell by cell, its column names over the columns —
  // never into three pricing cards as if each feature were a plan
  const mk = matrixWidth(orig.lists[0]);
  let matrix = null;
  if (mk) {
    // (a list of plans — "$9 /month" — is the design's column heads, not its rows)
    const li = candLists.findIndex((cl) => cellFields(cl).length === mk
      && !cellFields(cl).some((f) => /[$€£¥₹]/.test(String(((cl.demoItems || [])[0] || {})[f.field] ?? ''))));
    if (li < 0) {
      for (const it of orig.lists[0].items) for (const u of it.units) dropped.push({ role: u.role, text: u.text });
      orig = { ...orig, units: orig.units.filter((u) => u.list !== 0), lists: orig.lists.slice(1) };
    } else {
      matrix = { li, k: mk };
      const heads = orig.units.filter((u) => (u.list === null || u.list === undefined) && u.tag === 'th');
      const at = candLists[li].at;
      const over = slots.filter((x) => x.role === 'text' && !x.optional && x.at != null && at != null && x.at < at).slice(-(mk - 1));
      if (heads.length === mk - 1 && over.length === mk - 1) {
        heads.forEach((u, i) => { props.push([over[i].key, `<>${u.src}</>`]); carried.push({ role: 'text', text: u.text }); });
        orig = { ...orig, units: orig.units.filter((u) => !heads.includes(u)) };
        slots = slots.filter((x) => !over.includes(x));
      }
    }
  }
  const candGroups = cand.groups || [];
  const useLists = candLists.length && orig.lists.length;
  const useGroup = !useLists && candGroups.length && orig.lists.length;
  let flat = orig.units.filter((u) => !((useLists && u.list !== null && u.list < candLists.length) || (useGroup && u.list === 0)));
  const byRole = (arr, r) => arr.filter((x) => x.role === r);
  let flatSlots = useGroup ? slots.filter((x) => !x.group) : slots;
  // a role only one side uses reads as text: an owner's <blockquote> fills a design's <p>, a design's <cite> an owner's line
  for (const r of ['quote', 'label', 'figure']) {
    if (!flatSlots.some((x) => x.role === r)) flat = flat.map((u) => (u.role === r ? { ...u, role: 'text' } : u));
    if (!flat.some((u) => u.role === r)) flatSlots = flatSlots.map((x) => (x.role === r ? { ...x, role: 'text' } : x));
  }
  // a button whose label is a plain prop (`label = "Welcome"` shown in a <span>): the owner's button text is that label
  if (flat.length && flat.every((u) => u.role === 'action') && !flatSlots.some((x) => x.role === 'action') && flatSlots.some((x) => x.role === 'text')) {
    flat = flat.map((u) => ({ ...u, role: 'text' }));
  }
  // a design's headline is never left to demo copy while the owner wrote one short line of their own (a notice bar
  // into a call to action): that line is the headline
  if (!orig.units.some((u) => u.role === 'heading' || u.role === 'quote' || (u.list !== null && u.list !== undefined))
    && flatSlots.some((x) => x.role === 'heading' && !x.optional)) {
    const line = flat.find((u) => u.role === 'text' && u.text.length <= 100 && u.text.split(/\s+/).length >= 4);
    if (line) flat = flat.map((u) => (u === line ? { ...u, role: 'heading' } : u));
  }
  // the owner's list items go into a design's fixed slots whole, in order: a second testimonial never becomes the
  // first card's "role" line. An item that does not fit whole is left out (reported, never half-shown)
  if (!useLists && !useGroup && flat.some((u) => u.list !== null && u.list !== undefined)) {
    const cap = {};
    for (const x of flatSlots) cap[x.role] = (cap[x.role] || 0) + 1;
    for (const u of flat) if (u.list === null || u.list === undefined) cap[u.role] = (cap[u.role] || 0) - 1;
    const byItem = new Map();
    for (const u of flat) if (u.list !== null && u.list !== undefined) { const k = u.list + ':' + u.item; if (!byItem.has(k)) byItem.set(k, []); byItem.get(k).push(u); }
    const out = new Set();
    for (const units of byItem.values()) {
      if (units.length < 2) continue;                                   // single-unit items (badges, links) flow as before
      const need = {};
      for (const u of units) need[u.role] = (need[u.role] || 0) + 1;
      if (Object.entries(need).every(([r, n]) => (cap[r] || 0) >= n)) { for (const [r, n] of Object.entries(need)) cap[r] -= n; }
      else for (const u of units) out.add(u);
    }
    if (out.size) { for (const u of out) dropped.push({ role: u.role, text: u.text }); flat = flat.filter((u) => !out.has(u)); }
  }

  if (useGroup) {
    const items = orig.lists[0].items;
    // one row that holds every item beats spreading them (4 items: the 4-up row, not 2-up + half a 4-up);
    // otherwise rows fill in reading order. A row the items never reach is hidden whole.
    const fit = candGroups.length > 1 ? candGroups.filter((g) => g.count >= items.length).sort((a, b) => a.count - b.count)[0] : null;
    const use = fit ? [fit] : candGroups;
    let next = 0;
    for (const g of candGroups) {
      const gk = g.key;
      const active = use.includes(g);
      let filled = 0;
      for (let i = 0; i < g.count; i++) {
        const ms = slots.filter((x) => x.group === gk && x.member === i);
        if (!active || next >= items.length) {
          props.push([gk + 'Show' + (i + 1), 'false']);
          continue;
        }
        // a member is one card — or a column of rows (several headings): then consecutive items fill its rows, one each
        const textSl = ms.filter((x) => ITEM_CLASSES[0].includes(x.role));
        const rowsSl = [];
        for (const x of textSl) { if (!rowsSl.length || (x.role === 'heading' && rowsSl[rowsSl.length - 1].some((y) => y.role === 'heading'))) rowsSl.push([]); rowsSl[rowsSl.length - 1].push(x); }
        const multi = rowsSl.length > 1 && rowsSl.every((r) => r.some((y) => y.role === 'heading'));
        const packed = items.slice(next, next + (multi ? rowsSl.length : 1));
        next += packed.length;
        filled++;
        const place = (pairs, left, empty) => {
          for (const [u, x] of pairs) {
            props.push([x.key, `<>${u.src}</>`]);
            if (x.href && u.href) props.push([x.key + 'Href', u.href]);
            carried.push({ role: u.role, text: u.text });
          }
          for (const u of left) dropped.push({ role: u.role, text: u.text });
          for (const x of empty) {
            if (x.optional) props.push([x.key, 'false']);
            else demo.push({ role: x.role, key: x.key, text: x.demo });
          }
        };
        // headings and body text: row by row (inside a card, a title to the title, the longest text to the body)
        if (multi) {
          packed.forEach((it, r) => { const q = pairCard(it.units.filter((u) => ITEM_CLASSES[0].includes(u.role)), rowsSl[r]); place(q.pairs, q.left, q.empty); });
          for (const r of rowsSl.slice(packed.length)) place([], [], r);
        } else {
          const q = pairCard(packed.flatMap((it) => it.units.filter((u) => ITEM_CLASSES[0].includes(u.role))), [...textSl.filter((x) => !x.optional), ...textSl.filter((x) => x.optional)]);
          place(q.pairs, q.left, q.empty);
        }
        // prices, actions and list items pair among themselves, in order
        for (const cls of ITEM_CLASSES.slice(1)) {
          const o = packed.flatMap((it) => it.units.filter((u) => cls.includes(u.role))), sl = ms.filter((x) => cls.includes(x.role));
          place(o.slice(0, sl.length).map((u, k) => [u, sl[k]]), o.slice(sl.length), sl.slice(o.length));
        }
        const bs = ms.find((x) => x.role === 'bullets');
        const bullets = packed.flatMap((it) => it.bullets);
        if (bs) {
          // the owner's bullets, or none — a design's demo feature list is never presented as theirs
          props.push([bs.key, JSON.stringify(bullets)]);
          if (bullets.length) carried.push({ role: 'item', text: bullets.join(', ') });
        } else if (bullets.length) dropped.push({ role: 'item', text: bullets.join(', ') });
      }
      if (!filled && g.box) props.push([gk + 'BoxShow', 'false']);           // a row nothing reaches goes whole
      if (g.cols && active && filled && filled < g.count) props.push([gk + 'Cols', String(filled)]);
    }
    for (let i = next; i < items.length; i++) for (const u of items[i].units) dropped.push({ role: u.role, text: u.text });
  }

  // actions pair by kind first (the owner's CTA goes to the design's CTA button, not its eyebrow link)
  const kindOrder = (arr) => { const ctas = arr.filter((x) => x.sub !== 'link'), links = arr.filter((x) => x.sub === 'link'); return [ctas, links]; };
  for (const role of CONTENT_ROLES) {
    let o = byRole(flat, role), s = byRole(flatSlots, role);
    if (role === 'action') {
      const [oc, ol] = kindOrder(o), [sc, sl] = kindOrder(s);
      const nc = Math.min(oc.length, sc.length), nl = Math.min(ol.length, sl.length);
      const oRest = [...oc.slice(nc), ...ol.slice(nl)], sRest = [...sc.slice(nc), ...sl.slice(nl)];
      o = [...oc.slice(0, nc), ...ol.slice(0, nl), ...oRest];
      s = [...sc.slice(0, nc), ...sl.slice(0, nl), ...sRest];
    }
    s = [...s.filter((x) => !x.optional), ...s.filter((x) => x.optional)];   // a real subtitle slot first
    const n = Math.min(o.length, s.length);
    for (let i = 0; i < n; i++) {
      props.push([s[i].key, s[i].propName && !o[i].dynamic ? JSON.stringify(o[i].text) : `<>${o[i].src}</>`]);
      if (s[i].href && o[i].href) props.push([s[i].key + 'Href', o[i].href]);
      if (s[i].hrefProp && o[i].href) props.push(['@' + s[i].hrefProp, o[i].href]);
      carried.push({ role, text: o[i].text });
    }
    for (let i = n; i < o.length; i++) dropped.push({ role, text: o[i].text });
    for (let i = n; i < s.length; i++) {
      if (s[i].optional) { props.push([s[i].key, 'false']); continue; }
      // a prop-driven design's own words ("Design Systems") never stand in for the owner's: empty instead
      if (s[i].propName) { props.push([s[i].key, '""']); hidden.push(`demo ${role}: ${s[i].demo}`); continue; }
      // a design's extra demo button ("Get a Demo" -> "#") is hidden, never shown as the owner's offer
      if (s[i].hideable && !opts.keepDemoActions) { props.push([s[i].key + 'Show', 'false']); hidden.push(s[i].demo); continue; }
      demo.push({ role, key: s[i].key, text: s[i].demo });
    }
  }
  // a design's own bullet list outside any card ("UI/UX, Modern Design…") is not the owner's: emptied
  for (const x of flatSlots.filter((y) => y.role === 'bullets' && !y.group)) { props.push([x.key, '[]']); hidden.push(`demo list (${x.demo})`); }
  if ((cand.logoRows || []).length) hidden.push(`${cand.logoRows.length} row(s) of demo brand logos`);
  if ((cand.forms || []).length) hidden.push(`${cand.forms.length} design form(s) — not wired to anything`);

  if (useLists) {
    candLists.forEach((cl, li) => {
      const ol = orig.lists[li];
      if (!ol) return;
      const leftDemo = new Set(), leftHidden = new Set();
      const items = ol.items.map((it, ii) => {
        const obj = {};
        let units = it.units;
        const has = (arr, r) => arr.filter((u) => u.role === r).length;
        for (const r of ['quote', 'label', 'figure']) if (!cl.fields.some((f) => f.role === r)) units = units.map((u) => (u.role === r ? { ...u, role: 'text' } : u));
        const fr = (f) => (['quote', 'label', 'figure'].includes(f.role) && !units.some((u) => u.role === f.role) ? 'text' : f.role);
        // a FAQ row written as two paragraphs, a design with a question + answer: the first text is the title
        if (!has(units, 'heading') && cl.fields.some((f) => f.role === 'heading') && has(units, 'text') > cl.fields.filter((f) => f.role === 'text').length) {
          const first = units.find((u) => u.role === 'text');
          units = units.map((u) => (u === first ? { ...u, role: 'heading' } : u));
        }
        // the owner's photo is captioned by one of their words (`alt={m.name}` + `<p>{m.name}</p>`) and the design
        // does the same: that word goes to the design's captioning field — the name stays the name
        const capF = cl.fields.find((f) => f.role === 'imageAlt' && cl.fields.some((g) => g.field === f.field && CONTENT_ROLES.includes(g.role)));
        const cap = capF && it.images[0] && typeof it.images[0].alt === 'string' ? it.images[0].alt.replace(/^"|"$/g, '') : null;
        const capU = cap && units.find((u) => u.text === cap && u.role !== 'action');
        if (capU) { obj[capF.field] = unitValue(capU, orig.inner); carried.push({ role: capU.role, text: capU.text }); units = units.filter((u) => u !== capU); }
        if (matrix && matrix.li === li) {
          cellFields(cl).forEach((f, k) => { obj[f.field] = unitValue(it.units[k], orig.inner); carried.push({ role: it.units[k].role, text: it.units[k].text }); });
          units = [];
        }
        for (const role of CONTENT_ROLES) {
          let fields = cl.fields.filter((f) => fr(f) === role && !(f.field in obj));
          let vals = units.filter((u) => u.role === role);
          if (fields.length > 1 && vals.length > 1) {
            // name + role + quote, all text: when one of the design's own texts is clearly the long one (the quote),
            // the owner's longest text goes there; the rest keep document order (name, then role)
            const dl = (f) => String(((cl.demoItems || [])[0] || {})[f.field] || '').length;
            const ls = fields.map(dl);
            const vLong = vals.reduce((a, b) => (b.text.length > a.text.length ? b : a));
            const vShort = Math.min(...vals.map((v) => v.text.length));
            // …only when the owner's own words are that uneven too: "Nadia B." / "Founder" stay name, then role
            if (Math.min(...ls) > 0 && Math.max(...ls) >= 3 * Math.min(...ls) && vLong.text.length >= 2 * vShort && vLong.text.length >= 40) {
              const fLong = fields[ls.indexOf(Math.max(...ls))];
              fields = [fLong, ...fields.filter((f) => f !== fLong)];
              vals = [vLong, ...vals.filter((v) => v !== vLong)];
            }
          }
          fields.forEach((f, k) => { if (vals[k]) { obj[f.field] = unitValue(vals[k], orig.inner); carried.push({ role, text: vals[k].text }); } });
          for (let k = fields.length; k < vals.length; k++) dropped.push({ role, text: vals[k].text });
        }
        const d = (cl.demoItems || [])[ii % Math.max(1, (cl.demoItems || []).length)] || {};
        // every field the design shows as words (found by role, or only ever rendered as text) that the owner did not fill
        const shown = new Set([...cl.fields.filter((f) => CONTENT_ROLES.includes(f.role)).map((f) => f.field), ...(cl.textOnly || [])]);
        const ownPrice = it.units.some((u) => u.role === 'price');
        for (const f of shown) {
          if (f in obj || typeof d[f] !== 'string' || !d[f].trim()) continue;
          // the design's own "/month" beside the owner's price: theirs already says "€290 /month", or it is not a
          // subscription at all ("€24" for a product) — either way the design's period goes
          if (ownPrice && /^\s*(\/|per\s)\s*\w+\s*$/i.test(d[f])) { obj[f] = ''; continue; }
          if ((cl.textOnly || []).includes(f)) { leftDemo.add(d[f]); obj[f] = { __src: `<span data-dh-demo="">{${JSON.stringify(d[f])}}</span>` }; }
          // a field also read as a value (`{tier.period && <span>{tier.period}</span>}`) cannot carry a dash: it is
          // emptied — "€24 /month" on a product that is not a subscription would be a claim the owner never made
          else { obj[f] = ''; leftHidden.add(`${f}: ${d[f]}`); }
        }
        const hrefF = cl.fields.find((f) => f.role === 'href');
        const act = it.units.find((u) => u.role === 'action' && u.href);
        if (hrefF && act) obj[hrefF.field] = { __src: act.href };           // JS source: a quoted string or the owner's expression
        const bulletsF = cl.fields.find((f) => f.role === 'bullets');
        if (bulletsF && it.bullets.length) { obj[bulletsF.field] = it.bullets; carried.push({ role: 'item', text: it.bullets.join(', ') }); }
        // a plan's demo feature list is never presented as the owner's: theirs, or none
        else if (bulletsF && Array.isArray(d[bulletsF.field]) && d[bulletsF.field].every((x) => typeof x === 'string')) obj[bulletsF.field] = [];
        // a footer column's own links (`links: [{ label, href }]`): the owner's column links, in order
        const nested = bulletsF && !(bulletsF.field in obj) && Array.isArray(d[bulletsF.field]) && d[bulletsF.field][0] && typeof d[bulletsF.field][0] === 'object' ? d[bulletsF.field][0] : null;
        const lk = nested && Object.keys(nested).find((k) => /^(label|name|title|text)$/.test(k) && typeof nested[k] === 'string');
        const hk = nested && Object.keys(nested).find((k) => /^(href|url|link|to)$/.test(k) && typeof nested[k] === 'string');
        const acts = units.filter((u) => u.role === 'action' && u.href);
        if (lk && hk && acts.length) {
          obj[bulletsF.field] = { __src: '[' + acts.map((a) => `{ ${JSON.stringify(hk)}: ${a.href}, ${JSON.stringify(lk)}: ${itemValue(unitValue(a, orig.inner))} }`).join(', ') + ']' };
          for (const a of acts) { carried.push({ role: 'action', text: a.text }); const di = dropped.findIndex((x) => x.role === 'action' && x.text === a.text); if (di >= 0) dropped.splice(di, 1); }
        } else if (lk && hk) obj[bulletsF.field] = { __src: '[]' };      // a column with no links of the owner's: none of the design's
        const imgF = cl.fields.find((f) => f.role === 'image');
        if (imgF && it.images[0] && it.images[0].src) {
          obj[imgF.field] = { __src: it.images[0].src };
          carried.push({ role: 'image', text: it.images[0].alt ? String(it.images[0].alt).replace(/^"|"$/g, '') : it.images[0].src });
          // the owner's photo never carries a demo person's name as its alt text
          const altF = cl.fields.find((f) => f.role === 'imageAlt');
          if (altF && !(altF.field in obj)) obj[altF.field] = it.images[0].alt ? { __src: it.images[0].alt } : '';
        }
        else for (const im of it.images.filter((i) => i.src)) dropped.push({ role: 'image', text: im.alt ? String(im.alt).replace(/^"|"$/g, '') : im.src });
        return obj;
      });
      props.push([cl.key, listSrc(items)]);
      for (const t of leftDemo) demo.push({ role: 'list', key: cl.key, text: t });
      for (const t of leftHidden) hidden.push(`demo ${t} (emptied)`);
      if (ol.items.length !== cl.demoCount) demo.push({ role: 'list', key: cl.key, text: `${ol.items.length} of your items (design shows ${cl.demoCount})` });
    });
  }

  // a design's own copyright line never survives: the owner's, or © <year> <brand>
  if (opts.brand) {
    for (const d of demo.filter((x) => x.role === 'copyright')) {
      props.push([d.key, `<>© {new Date().getFullYear()} ${opts.brand.replace(/[{}<>]/g, '')}</>`]);
      demo.splice(demo.indexOf(d), 1);
      hidden.push(`demo copyright → © ${opts.brand}`);
    }
  }
  let oi = orig.images;
  const own = ownerLogos(orig);
  if ((cand.logoSwaps || []).length && own.length >= 2) {
    const tag = (im) => im.jsx || `<img src={${im.src}}${im.alt ? ` alt={${im.alt}}` : ' alt=""'} className="h-7 w-auto object-contain" />`;
    for (const k of cand.logoSwaps) props.push([k, `<>${own.map(tag).join('')}</>`]);
    for (const im of own) carried.push({ role: 'image', text: im.alt ? String(im.alt).replace(/^"|"$/g, '') : im.src });
    oi = oi.filter((im) => !own.includes(im));
    // a list of logos went whole into the row: its names are not left over as loose text
    const listed = new Set(own);
    for (const l of orig.lists) for (const it of l.items) if (it.images.some((im) => listed.has(im))) for (const u of it.units) { const di = dropped.findIndex((x) => x.text === u.text); if (di >= 0) dropped.splice(di, 1); }
  } else if ((cand.logoSwaps || []).length) for (const k of cand.logoSwaps) props.push([k, '<></>']);
  const si = slots.filter((x) => x.role === 'image');
  for (let i = 0; i < Math.min(oi.length, si.length); i++) {
    if (oi[i].src) props.push([si[i].key, oi[i].src]);
    if (oi[i].alt) props.push([si[i].key + 'Alt', oi[i].alt]);
    carried.push({ role: 'image', text: oi[i].alt ? String(oi[i].alt).replace(/^"|"$/g, '') : oi[i].src });
  }
  for (let i = si.length; i < oi.length; i++) dropped.push({ role: 'image', text: oi[i].alt ? String(oi[i].alt).replace(/^"|"$/g, '') : oi[i].src });
  for (let i = oi.length; i < si.length; i++) {
    if (si[i].localDemo && opts.placeholder) {
      props.push([si[i].key, JSON.stringify(opts.placeholder)]);
      demo.push({ role: 'image', key: si[i].key, text: 'image placeholder — add your own' });
    }
  }
  const op = orig.inputs, sp = slots.filter((x) => x.role === 'placeholder');
  for (let i = 0; i < Math.min(op.length, sp.length); i++) if (op[i].placeholder) props.push([sp[i].key, op[i].placeholder]);
  return { props, carried, dropped, demo, hidden, ...(lost ? { lost } : {}) };
}

export function contentProp(prop, props) {
  // `@title` goes to the component's own prop; everything else into the one content object
  const own = props.filter(([k]) => k.startsWith('@')), rest = props.filter(([k]) => !k.startsWith('@'));
  const attrs = own.map(([k, v]) => ` ${k.slice(1)}={${v}}`).join('');
  return attrs + (rest.length ? ` ${prop}={{ ${rest.map(([k, v]) => `${k}: ${v}`).join(', ')} }}` : '');
}

/** How much content the original holds (the fit denominator). */
export function contentCount(orig) {
  return orig.units.length + orig.images.length + orig.lists.reduce((n, l) => n + l.items.reduce((m, it) => m + it.bullets.length + it.images.filter((i) => i.src).length, 0), 0);
}

export function shapeOf(u) {
  const c = (r) => u.units.filter((x) => x.role === r).length;
  return { heading: c('heading'), text: c('text'), action: c('action'), item: c('item'), image: u.images.length, lists: u.lists.length };
}
