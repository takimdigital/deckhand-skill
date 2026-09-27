/**
 * vet.mjs — a component registry enters try-on only after it is measured against written criteria.
 *
 *   tryon registry vet --index https://x.dev/r/registry.json --repo owner/name [--id x]   report only
 *   tryon registry add  …same…                                                           report, then add
 *
 * Hard criteria (any fail = refused, with the reason and what would be accepted):
 *   not refused   not on the refused list (data/registries.json: AGPL, Commons Clause, paid tiers, bot walls)
 *   licence       the source repository's licence is permissive (data/licenses.json — the same policy as bases)
 *   schema        the index is a shadcn-schema registry with ui/block/component items
 *   usable        at least one item maps to a try-on slot (hero, pricing, button…)
 *   free          sampled items download without an account and carry their source (no 401/402/403,
 *                 no content-less "pro" items) — a paywall is refused, whatever the licence says
 * Accepted -> ~/.deckhand/registries.json (config) + ~/.deckhand/catalog/registry-<id>.json (its items),
 * which the catalog loads beside the shipped one. Same inputs -> same verdict.
 */
import fs from 'node:fs';
import path from 'node:path';
import { getText } from './registry.mjs';
import { mapShadcnItems, baseOf } from './regmap.mjs';
import { SKILL_DIR, libraryDir } from './catalog.mjs';

const POLICY = JSON.parse(fs.readFileSync(path.join(SKILL_DIR, 'data', 'licenses.json'), 'utf8'));
const REGISTRIES = JSON.parse(fs.readFileSync(path.join(SKILL_DIR, 'data', 'registries.json'), 'utf8'));
const deckhandHome = () => path.dirname(libraryDir());

export const acceptable = () => `Accepted: a shadcn-schema registry (registry.json with ui/block/component items) whose source repository has a permissive licence (${Object.keys(POLICY.accepted).join(', ')}), whose items download without an account, and that is not on the refused list.`;

const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40);

export async function vetRegistry({ index, repo, id, item: itemTemplate, sample = 3 }) {
  const fails = [], warns = [], passes = [];
  const check = (ok, cid, good, bad, hard = true) => (ok ? passes : hard ? fails : warns).push({ id: cid, detail: ok ? good : bad });
  if (!index || !/^https:\/\//.test(index)) throw Object.assign(new Error('USAGE: --index https://…/registry.json'), { code: 'USAGE' });
  const host = new URL(index).hostname;
  const rid = slug(id || host.replace(/^www\./, '').split('.')[0]);
  const refused = REGISTRIES.refused.find((r) => (r.hosts || []).some((h) => host === h || host.endsWith('.' + h)));
  check(!refused, 'not refused', 'not on the refused list', refused ? `on the refused list: ${refused.id} — ${refused.reason}` : '');
  const known = REGISTRIES.registries.find((r) => r.id === rid || (r.index || '').includes(host));
  if (known) warns.push({ id: 'already-shipped', detail: `${known.id} is already in the shipped catalog` });

  // licence: from the source repository (a website's footer is not evidence)
  let lic = null;
  if (!repo) {
    check(false, 'licence', '', 'no source repository given (--repo owner/name): a licence must be evidenced by the repository, not assumed');
  } else {
    let apiErr = null;
    try {
      const meta = JSON.parse(await getText(`https://api.github.com/repos/${repo}`));
      lic = (meta.license && meta.license.spdx_id) || 'NONE';
      if (meta.archived) warns.push({ id: 'archived', detail: `${repo} is archived` });
    } catch (e) { apiErr = e; }
    // the API out of reach (a rate limit, a proxy): the repository's own LICENSE file is the same evidence
    if (!lic) {
      const f = await licenceFromFile(repo);
      if (f) { lic = f.spdx; warns.push({ id: 'licence-from-file', detail: `GitHub's API was out of reach; read ${repo}/${f.file}` }); }
      else check(false, 'licence', '', `could not read ${repo} on GitHub (${apiErr.message.split(' ').slice(0, 3).join(' ')}) nor its LICENSE file`);
    }
    if (lic) check(lic in POLICY.accepted, 'licence', `${lic} — ${POLICY.accepted[lic] || ''}`, `${lic}: ${POLICY.refused[lic] || POLICY.refused.OTHER}`);
  }

  // schema + usable items
  let idx = null;
  try { idx = JSON.parse(await getText(index)); } catch (e) { check(false, 'schema', '', `the index did not load as JSON (${e.message.split(' ').slice(0, 3).join(' ')})`); }
  const itemUrl = itemTemplate || index.replace(/registry\.json$/, '{name}.json');
  const reg = { id: rid, index, item: itemUrl, license: lic || 'UNKNOWN', base: 'any', repo: repo || null };
  let items = [];
  if (idx) {
    const typed = (idx.items || []).filter((it) => /registry:(ui|block|component)$/.test(String(it.type || '')));
    check(typed.length > 0, 'schema', `${typed.length} ui/block/component items`, 'no registry:ui / registry:block / registry:component items — not a shadcn-schema registry');
    items = mapShadcnItems(reg, idx, null, baseOf(idx.items || []));
    check(items.length > 0, 'usable', `${items.length} items map to try-on slots`, 'none of its items maps to a try-on slot (hero, pricing, button…)');
  }

  // free: sample real downloads
  if (items.length) {
    const picks = [...items].sort((a, b) => a.n.localeCompare(b.n)).filter((_, i, a) => i % Math.max(1, Math.floor(a.length / sample)) === 0).slice(0, sample);
    const bad = [];
    for (const it of picks) {
      try {
        const doc = JSON.parse(await getText(it.json));
        const content = (doc.files || []).some((f) => typeof f.content === 'string' && f.content.trim().length > 20);
        if (!content) bad.push(`${it.n}: no source in the item (a "pro"/locked item)`);
      } catch (e) { bad.push(`${it.n}: ${e.status ? 'HTTP ' + e.status : e.message.split(' ')[0]}`); }
    }
    const walled = bad.filter((b) => /HTTP 40[123]|locked/.test(b));
    check(!walled.length, 'free', `${picks.length} sampled items download with their source`, `paywalled or account-only: ${walled.join('; ')}`);
    const other = bad.filter((b) => !walled.includes(b));
    if (other.length) warns.push({ id: 'unreachable', detail: other.join('; ') });
  }
  const ok = !fails.length;
  return { registry: rid, index, repo: repo || null, verdict: ok ? 'accepted' : 'refused', fails, warnings: warns, passes,
    items: items.length, base: items[0] ? items[0].base : null, ...(ok ? {} : { acceptable: acceptable() }), _reg: reg, _items: items };
}

/** The licence a repository's own LICENSE file states (main or master), or null when there is none to read. */
export async function licenceFromFile(repo) {
  for (const branch of ['main', 'master']) {
    for (const f of ['LICENSE', 'LICENSE.md', 'LICENSE.txt', 'license', 'license.md']) {
      let text;
      try { text = await getText(`https://raw.githubusercontent.com/${repo}/${branch}/${f}`); } catch { continue; }
      return { spdx: spdxOf(text), file: `${branch}/${f}` };
    }
  }
  return null;
}

/** A licence text -> its SPDX id. A permissive text with a Commons Clause (or any restriction on selling) is not
 *  permissive: checked first. Unknown -> OTHER (refused, never guessed). */
export function spdxOf(text) {
  const t = String(text || '').replace(/\s+/g, ' ');
  if (/Commons Clause|the Software does not include the right to Sell/i.test(t)) return 'OTHER';
  if (/GNU AFFERO GENERAL PUBLIC LICENSE/i.test(t)) return 'AGPL-3.0';
  if (/GNU LESSER GENERAL PUBLIC LICENSE/i.test(t)) return /Version 2\.1/i.test(t) ? 'LGPL-2.1' : 'LGPL-3.0';
  if (/GNU GENERAL PUBLIC LICENSE/i.test(t)) return /Version 2,/i.test(t) ? 'GPL-2.0' : 'GPL-3.0';
  if (/Mozilla Public License,? (version )?2\.0/i.test(t)) return 'MPL-2.0';
  if (/Business Source License/i.test(t)) return 'BUSL-1.1';
  if (/Server Side Public License/i.test(t)) return 'SSPL-1.0';
  if (/Apache License,? Version 2\.0/i.test(t)) return 'Apache-2.0';
  if (/Permission is hereby granted, free of charge, to any person obtaining a copy/i.test(t)) return 'MIT';
  if (/Redistribution and use in source and binary forms/i.test(t)) return /Neither the name/i.test(t) ? 'BSD-3-Clause' : 'BSD-2-Clause';
  if (/Permission to use, copy, modify, and\/or distribute this software for any purpose with or without fee is hereby granted/i.test(t)) {
    return /provided that the above copyright notice and this permission notice appear/i.test(t) ? 'ISC' : '0BSD';
  }
  if (/This is free and unencumbered software released into the public domain/i.test(t)) return 'Unlicense';
  return 'OTHER';
}

export async function addRegistry(opts) {
  const v = await vetRegistry(opts);
  const { _reg, _items, ...report } = v;
  if (v.verdict !== 'accepted') {
    throw Object.assign(new Error(`${v.registry} does not meet the registry criteria: ` + v.fails.map((f) => f.detail).join('; ')), { code: 'REFUSED', report });
  }
  const cfgPath = path.join(deckhandHome(), 'registries.json');
  let cfg = { registries: [] };
  try { cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8')); } catch { /* new */ }
  cfg.registries = cfg.registries.filter((r) => r.id !== _reg.id).concat([{ ..._reg, vetted: { at: new Date().toISOString(), warnings: v.warnings.map((w) => w.id) } }]);
  fs.mkdirSync(path.dirname(cfgPath), { recursive: true });
  fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 1));
  const catDir = path.join(deckhandHome(), 'catalog');
  fs.mkdirSync(catDir, { recursive: true });
  fs.writeFileSync(path.join(catDir, `registry-${_reg.id}.json`), JSON.stringify({ registry: _reg.id, items: _items }));
  return { ...report, added: true, config: cfgPath, catalog: path.join(catDir, `registry-${_reg.id}.json`) };
}

export function listRegistries() {
  try { return JSON.parse(fs.readFileSync(path.join(deckhandHome(), 'registries.json'), 'utf8')).registries; } catch { return []; }
}

export function removeRegistry(id) {
  const cfgPath = path.join(deckhandHome(), 'registries.json');
  const cfg = { registries: listRegistries().filter((r) => r.id !== id) };
  fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 1));
  fs.rmSync(path.join(deckhandHome(), 'catalog', `registry-${id}.json`), { force: true });
  return { removed: id };
}
