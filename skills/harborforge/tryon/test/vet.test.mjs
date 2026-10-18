import test from 'node:test';
import { scratch } from './helpers.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { keyOf } from '../lib/registry.mjs';

// a private fixture world: fake registries and a fake GitHub API, replayed offline
const FX = scratch('dh-vet-fx-');
const HOME = scratch('dh-vet-home-');
process.env.DH_FIXTURES = FX;
process.env.DH_CACHE = scratch('dh-vet-cache-');
process.env.DECKHAND_LIBRARY = path.join(HOME, 'library');
const put = (url, body, status) => fs.writeFileSync(path.join(FX, keyOf(url) + (status ? '.' + status : '.txt')), status ? url : (typeof body === 'string' ? body : JSON.stringify(body)));
const index = (items) => ({ name: 'x', items });
const src = 'export function Button(){ return <button className="rounded-md bg-primary px-4 py-2">Go</button> }';

put('https://good-ui.dev/r/registry.json', index([
  { name: 'button-glow', type: 'registry:ui', dependencies: ['@radix-ui/react-slot'] },
  { name: 'hero-split', type: 'registry:block', dependencies: [] },
  { name: 'use-thing', type: 'registry:hook' },
]));
put('https://good-ui.dev/r/button-glow.json', { name: 'button-glow', files: [{ path: 'ui/button-glow.tsx', content: src }] });
put('https://good-ui.dev/r/hero-split.json', { name: 'hero-split', files: [{ path: 'blocks/hero-split.tsx', content: src }] });
put('https://api.github.com/repos/good/ui', { license: { spdx_id: 'MIT' }, archived: false });
put('https://agpl-ui.dev/r/registry.json', index([{ name: 'hero-a', type: 'registry:block' }]));
put('https://agpl-ui.dev/r/hero-a.json', { files: [{ path: 'a.tsx', content: src }] });
put('https://api.github.com/repos/agpl/ui', { license: { spdx_id: 'AGPL-3.0' } });
put('https://pro-ui.dev/r/registry.json', index([{ name: 'hero-pro', type: 'registry:block' }, { name: 'pricing-pro', type: 'registry:block' }]));
put('https://pro-ui.dev/r/hero-pro.json', null, 401);
put('https://pro-ui.dev/r/pricing-pro.json', { files: [{ path: 'p.tsx' }] });
put('https://api.github.com/repos/pro/ui', { license: { spdx_id: 'MIT' } });

const { vetRegistry, addRegistry, listRegistries, removeRegistry } = await import('../lib/vet.mjs');
const { loadCatalog } = await import('../lib/catalog.mjs');

test('a permissive, free, shadcn-schema registry is accepted, indexed and loaded by the catalog', async () => {
  const v = await vetRegistry({ index: 'https://good-ui.dev/r/registry.json', repo: 'good/ui' });
  assert.equal(v.verdict, 'accepted');
  assert.equal(v.items, 2);                                          // the hook maps to no slot
  assert.equal(v.base, 'radix');
  const r = await addRegistry({ index: 'https://good-ui.dev/r/registry.json', repo: 'good/ui' });
  assert.equal(r.added, true);
  const ids = loadCatalog().filter((i) => i.r === 'good-ui').map((i) => i.id).sort();
  assert.deepEqual(ids, ['good-ui/button-glow@radix', 'good-ui/hero-split@radix']);
  assert.deepEqual(listRegistries().map((x) => x.id), ['good-ui']);
  removeRegistry('good-ui');
  assert.equal(loadCatalog().filter((i) => i.r === 'good-ui').length, 0);
});

test('refused with the reason and what is acceptable: copyleft, paywall, no licence evidence, refused list', async () => {
  const agpl = await vetRegistry({ index: 'https://agpl-ui.dev/r/registry.json', repo: 'agpl/ui' });
  assert.equal(agpl.verdict, 'refused');
  assert.match(agpl.fails.find((f) => f.id === 'licence').detail, /AGPL-3.0: network copyleft/);
  assert.match(agpl.acceptable, /permissive licence/);
  const pro = await vetRegistry({ index: 'https://pro-ui.dev/r/registry.json', repo: 'pro/ui' });
  assert.equal(pro.verdict, 'refused');
  assert.match(pro.fails.find((f) => f.id === 'free').detail, /HTTP 401.*locked|locked.*HTTP 401|HTTP 401/);
  const noRepo = await vetRegistry({ index: 'https://good-ui.dev/r/registry.json' });
  assert.match(noRepo.fails.find((f) => f.id === 'licence').detail, /no source repository given/);
  put('https://ui.aceternity.com/registry.json', index([]));
  const listed = await vetRegistry({ index: 'https://ui.aceternity.com/registry.json', repo: 'good/ui' });
  assert.match(listed.fails.find((f) => f.id === 'not refused').detail, /aceternity — custom licence/);
  await assert.rejects(addRegistry({ index: 'https://agpl-ui.dev/r/registry.json', repo: 'agpl/ui' }), (e) => e.code === 'REFUSED' && e.report.verdict === 'refused');
  assert.deepEqual(listRegistries(), []);
});
