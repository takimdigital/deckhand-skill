'use strict';
/**
 * ast.cjs — source-exact parsing for try-on.
 *
 * Contract: every node carries `start`/`end` (UTF-16 offsets into the exact text that was parsed),
 * so every edit is a string splice on the original bytes: no reprint, no formatting drift.
 * Parser = vendored @babel/parser (zero dependencies). The project's own TypeScript is NOT used:
 * typescript@7 ships no JS compiler API, which silently broke the v1 engine on fresh projects.
 */
const parser = require('../vendor/babel-parser.cjs');

const BASE_PLUGINS = ['jsx', 'typescript'];
const RETRY_PLUGINS = [['jsx', 'typescript', 'decorators-legacy'], ['jsx', 'flow'], ['jsx']];

function pluginsFor(file) {
  if (/\.tsx$/i.test(file)) return [BASE_PLUGINS, ['jsx', 'typescript', 'decorators-legacy']];
  if (/\.(ts|mts|cts)$/i.test(file)) return [['typescript'], ['typescript', 'decorators-legacy']];
  return [['jsx'], ...RETRY_PLUGINS];
}

/** Parse or throw a typed error (code PARSE_FAILED) carrying the first parser message. */
function parse(file, text) {
  let lastErr = null;
  for (const plugins of pluginsFor(file)) {
    try {
      return parser.parse(text, {
        sourceType: 'module',
        sourceFilename: file,
        allowReturnOutsideFunction: true,
        allowImportExportEverywhere: true,
        allowAwaitOutsideFunction: true,
        errorRecovery: false,
        plugins,
      });
    } catch (e) {
      lastErr = e;
    }
  }
  const err = new Error('PARSE_FAILED: ' + file + ': ' + (lastErr && lastErr.message));
  err.code = 'PARSE_FAILED';
  throw err;
}

/** Depth-first walk; `enter(node, parent, key)` returning false skips the subtree. */
function walk(node, enter, parent = null, key = null) {
  if (!node || typeof node.type !== 'string') return;
  if (enter(node, parent, key) === false) return;
  for (const k of Object.keys(node)) {
    if (k === 'loc' || k === 'start' || k === 'end' || k === 'extra' || k === 'leadingComments'
      || k === 'trailingComments' || k === 'innerComments' || k === 'range') continue;
    const v = node[k];
    if (Array.isArray(v)) {
      for (const c of v) if (c && typeof c.type === 'string') walk(c, enter, node, k);
    } else if (v && typeof v.type === 'string') {
      walk(v, enter, node, k);
    }
  }
}

/** `<motion.div>` -> "motion.div", `<svg:rect>` -> "svg:rect", `<Foo>` -> "Foo". */
function jsxName(n) {
  if (!n) return '';
  if (n.type === 'JSXIdentifier') return n.name;
  if (n.type === 'JSXMemberExpression') return jsxName(n.object) + '.' + jsxName(n.property);
  if (n.type === 'JSXNamespacedName') return n.namespace.name + ':' + n.name.name;
  return '';
}

const isHostName = (name) => /^[a-z]/.test(name) && !name.includes('.');

/** 1-based line/col -> offset. */
function offsetOf(text, line, col) {
  let off = 0;
  for (let l = 1; l < line; l++) {
    const i = text.indexOf('\n', off);
    if (i === -1) return -1;
    off = i + 1;
  }
  return off + Math.max(0, col - 1);
}

/** The JSXElement whose opening `<` sits exactly at (line, col), 1-based. */
function findElementAt(ast, text, line, col) {
  const target = offsetOf(text, line, col);
  let hit = null;
  walk(ast, (node) => {
    if (hit) return false;
    if (node.end < target || node.start > target) return false;
    if (node.type === 'JSXElement' && node.start === target) { hit = node; return false; }
    return true;
  });
  return hit;
}

/** Innermost JSXElement containing `offset`. */
function elementContaining(ast, offset) {
  let best = null;
  walk(ast, (node) => {
    if (node.end < offset || node.start > offset) return false;
    if (node.type === 'JSXElement') best = node;
    return true;
  });
  return best;
}

function attr(el, name) {
  const op = el.openingElement || el;
  for (const a of op.attributes || []) {
    if (a.type === 'JSXAttribute' && a.name && jsxName(a.name) === name) return a;
  }
  return null;
}

/** Literal value of an attribute (string or {"string"} / {`tpl`} without expressions), else null. */
function attrLiteral(a) {
  if (!a || !a.value) return null;
  const v = a.value;
  if (v.type === 'StringLiteral') return v.value;
  if (v.type === 'JSXExpressionContainer') {
    const e = v.expression;
    if (e.type === 'StringLiteral') return e.value;
    if (e.type === 'TemplateLiteral' && e.expressions.length === 0) return e.quasis.map((q) => q.value.cooked).join('');
  }
  return null;
}

function lineCol(text, offset) {
  let line = 1, last = 0;
  for (let i = 0; i < offset; i++) if (text.charCodeAt(i) === 10) { line++; last = i + 1; }
  return { line, col: offset - last + 1 };
}

module.exports = { parse, walk, jsxName, isHostName, offsetOf, findElementAt, elementContaining, attr, attrLiteral, lineCol };
