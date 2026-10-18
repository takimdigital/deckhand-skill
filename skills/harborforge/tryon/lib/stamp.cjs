'use strict';
/**
 * stamp.cjs — the dev-only source map from DOM to JSX.
 *
 * Every JSX opening element gets `data-dh="<rel/path.tsx>:<line>:<col>"` inserted right after its
 * tag name (before any spread), so:
 *   - a host element (`<section>`) carries its own source location into the DOM;
 *   - a component usage (`<Button>`) passes its usage location as a prop; components that spread
 *     props onto their root (every shadcn primitive) let the USAGE site win in the DOM, which is the
 *     site the owner clicked.
 * AST-exact (vendored babel): no regex over source, so generics (`useState<T>()`), strings, comments
 * and multi-line tags are never touched. A file that fails to parse is returned unchanged — the
 * bundler reports the real error itself.
 */
const { parse, walk, jsxName } = require('./ast.cjs');

// React built-ins that reject or warn on unknown props; `<>` fragments have no name and are skipped.
const SKIP = new Set(['Fragment', 'React.Fragment', 'StrictMode', 'React.StrictMode', 'Suspense',
  'React.Suspense', 'Profiler', 'React.Profiler', 'Activity', 'ViewTransition', 'html', 'head',
  'script', 'style', 'meta', 'link', 'title', 'base', 'noscript', 'template', 'slot']);

const ATTR = 'data-dh';

function shouldSkip(name) {
  if (!name || SKIP.has(name)) return true;
  return /\.(Provider|Consumer)$/.test(name);
}

/**
 * Stamp a source file. `rel` is the posix path relative to the project root (what the DOM shows).
 * Returns { code, count }.
 */
function stamp(code, rel) {
  if (!code || code.indexOf('<') === -1) return { code, count: 0 };
  let ast;
  try {
    ast = parse(rel, code);
  } catch {
    return { code, count: 0 };
  }
  const inserts = [];
  walk(ast, (node) => {
    if (node.type !== 'JSXOpeningElement') return true;
    const name = jsxName(node.name);
    if (shouldSkip(name)) return true;
    for (const a of node.attributes) {
      if (a.type === 'JSXAttribute' && a.name && a.name.name === ATTR) return true;
    }
    const after = node.typeArguments || node.typeParameters || node.name;
    const { line, column } = node.loc.start;
    inserts.push({ at: after.end, text: ' ' + ATTR + '="' + rel + ':' + line + ':' + (column + 1) + '"' });
    return true;
  });
  if (!inserts.length) return { code, count: 0 };
  inserts.sort((a, b) => b.at - a.at);
  let out = code;
  for (const ins of inserts) out = out.slice(0, ins.at) + ins.text + out.slice(ins.at);
  return { code: out, count: inserts.length };
}

/** Parse a stamp value "rel/path.tsx:12:5" (the path may itself contain ':' on Windows drives). */
function parseStamp(value) {
  const m = /^(.*):(\d+):(\d+)$/.exec(String(value || ''));
  if (!m) return null;
  return { file: m[1], line: Number(m[2]), col: Number(m[3]) };
}

module.exports = { stamp, parseStamp, ATTR };
