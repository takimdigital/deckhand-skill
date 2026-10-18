/**
 * Deckhand try-on — Vite plugin (dev server only). Usage in vite.config:
 *   import dhTryon from '<skill>/tryon/vite.mjs'
 *   plugins: [dhTryon(), react()]
 * `tryon setup` writes this for you (journaled; `tryon clean` removes it).
 */
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { stamp } = require('./lib/stamp.cjs');

export default function dhTryon(opts = {}) {
  let root = opts.root || process.cwd();
  return {
    name: 'deckhand-tryon-stamp',
    apply: 'serve',
    enforce: 'pre',
    configResolved(cfg) { root = opts.root || cfg.root; },
    transform(code, id) {
      const file = id.split('?')[0];
      if (!/\.(jsx|tsx)$/.test(file) || /[\\/]node_modules[\\/]/.test(file)) return null;
      const rel = path.relative(root, file).split(path.sep).join('/');
      if (!rel || rel.startsWith('..')) return null;
      const out = stamp(code, rel);
      return out.count ? { code: out.code, map: null } : null;
    },
  };
}
