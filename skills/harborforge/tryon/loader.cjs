'use strict';
/**
 * Deckhand try-on stamp loader — webpack AND Turbopack (Next.js `turbopack.rules`).
 * Dev-only twice over: `setup` registers it only under NODE_ENV=development, and it is inert here
 * outside development (a Turbopack rule `condition` is a matcher, not an env gate).
 */
const path = require('path');
const { stamp } = require('./lib/stamp.cjs');

module.exports = function deckhandStampLoader(source) {
  const cb = typeof this.async === 'function' ? this.async() : null;
  const done = (out) => (cb ? cb(null, out) : out);
  if (process.env.NODE_ENV !== 'development') return done(source);

  const opts = (this.getOptions && this.getOptions()) || {};
  const root = path.resolve(opts.root || this.rootContext || process.cwd());
  const file = String(this.resourcePath || '');
  if (!/\.(jsx|tsx|js)$/.test(file)) return done(source);
  const norm = file.replace(/\\/g, '/');
  if (/\/(node_modules|\.next|\.deckhand)\//.test(norm)) return done(source);
  const rel = path.relative(root, file).split(path.sep).join('/');
  if (!rel || rel.startsWith('..')) return done(source);
  return done(stamp(String(source), rel).code);
};
