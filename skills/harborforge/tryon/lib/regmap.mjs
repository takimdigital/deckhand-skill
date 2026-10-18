/**
 * regmap.mjs — one mapping from a shadcn-schema registry index to catalog items, used by the maintainer
 * build (catalog-build.mjs) and by an owner's vetted registries (`tryon registry add`): same rules, same ids.
 */
import { slotFromName, kindOf } from './slots.mjs';

/** reg: { id, item (url template with {name}/{style}), license, mirror?, gh?, free_types? } */
export function mapShadcnItems(reg, idx, style = null, base = 'any') {
  const out = [];
  for (const it of (idx && idx.items) || []) {
    const type = String(it.type || '');
    if (!/registry:(ui|block|component)$/.test(type)) continue;
    if (reg.free_types && !reg.free_types.includes(type)) continue;
    const slot = (type === 'registry:ui' && slotFromName(it.name)) || slotFromName(it.name) || slotFromName((it.categories || []).join('-'));
    if (!slot) continue;
    const targetsUtils = (it.files || []).some((f) => /lib\/utils/.test(String(f.target || f.path || '')) && type !== 'registry:ui');
    if (targetsUtils) continue;
    const item = {
      id: `${reg.id}/${it.name}@${base}`, r: reg.id, n: it.name, base, slot, kind: kindOf(slot),
      t: it.title || it.name, deps: it.dependencies || [], rdeps: it.registryDependencies || [],
      json: reg.item.replace('{style}', style || '').replace('{name}', it.name), lic: reg.license,
    };
    if (style) item.style = style;
    if (reg.mirror) item.mirror = reg.mirror.replace('{style}', style || '').replace('{name}', it.name);
    if (reg.gh && (it.files || []).length) item.ghFiles = it.files.map((f) => `${reg.gh}/${f.path}`);
    out.push(item);
  }
  return out;
}

/** The primitive base a registry's items are written for, from their dependencies. */
export function baseOf(items) {
  const deps = items.flatMap((i) => i.dependencies || i.deps || []);
  const radix = deps.some((d) => /^@radix-ui\/|^radix-ui$/.test(d));
  const baseui = deps.some((d) => /^@base-ui-components\/react|^@base-ui\/react/.test(d));
  return radix && !baseui ? 'radix' : baseui && !radix ? 'base-ui' : 'any';
}

/**
 * Tailark ships every hero's navbar as its own file (`header.tsx`, `HeroHeader`) beside the hero: each one becomes
 * a navbar design (a hero swap strips it as chrome, so it is never shown twice). Derived from the hero items.
 */
export function navbarsFromHeroes(items) {
  const out = [];
  for (const h of items) {
    if (h.r !== 'tailark-oss' || h.slot !== 'hero' || !h.gh || !(h.rdeps || []).some((d) => /-header$/.test(d))) continue;
    const n = `${h.n}-header`;
    out.push({
      id: `tailark-oss/${n}@${h.base}`, r: 'tailark-oss', n, base: h.base, slot: 'navbar', kind: kindOf('navbar'),
      t: String(h.t || n).replace(/hero section/, 'header'), deps: [],
      rdeps: (h.rdeps || []).filter((d) => /-(button|logo)$/.test(d)),
      gh: h.gh.replace(/[^/]+$/, 'header.tsx'), json: h.json ? h.json + '-header' : undefined, lic: h.lic,
    });
  }
  return out;
}
