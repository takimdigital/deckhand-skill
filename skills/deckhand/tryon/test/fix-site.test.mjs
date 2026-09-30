// Fix package 4: compose keeps the owner's words / reuses its folders; seo apply writes hreflang for path-prefixed languages.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { tempSite, offline, scratch, read } from './helpers.mjs';
import { seoApply } from '../lib/seo.mjs';

const COMPOSE = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'compose.mjs');
offline();

function compose(dir, page, sections, extra = []) {
  const r = spawnSync(process.execPath, [COMPOSE, '--project', dir, '--page', page, '--sections', sections, '--copy', '.deckhand/copy.json', '--install', 'no', ...extra],
    { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], env: process.env });
  return JSON.parse(r.stdout.trim().split('\n').pop());
}
function siteWith(copy) {
  const dir = tempSite();
  fs.mkdirSync(path.join(dir, '.deckhand'), { recursive: true });
  fs.writeFileSync(path.join(dir, '.deckhand', 'copy.json'), JSON.stringify(copy));
  return dir;
}

test('compose never drops the owner text silently: a dropped list and a PENDING next step', () => {
  const dir = siteWith({ hero: { heading: 'Hello bakers', text: ['First paragraph of the owner.', 'Second paragraph that is long.'], actions: [{ label: 'Order', href: '/order' }] } });
  const o = compose(dir, 'app/page.tsx', 'hero');
  const lost = o.sections[0].dropped;
  assert.deepEqual(o.dropped.map((d) => d.text), lost);
  if (lost.length) {
    assert.match(o.next, /PENDING/);
    assert.ok(o.pending.length >= 1 && o.pending[0].where);
  }
});

test('compose reuses the staged folders of the same page instead of -2 copies', () => {
  const dir = siteWith({ hero: { heading: 'Hello bakers', text: ['One line.'] } });
  compose(dir, 'app/en/page.tsx', 'hero');
  const first = fs.readdirSync(path.join(dir, 'components/sections')).sort();
  compose(dir, 'app/en/page.tsx', 'hero');
  assert.deepEqual(fs.readdirSync(path.join(dir, 'components/sections')).sort(), first);
  assert.ok(!first.some((n) => /-2$/.test(n)));
});

test('compose --chrome yes adds navbar and footer; without it an inner page says where chrome comes from', () => {
  const dir = siteWith({ hero: { heading: 'Hello bakers', text: ['One line.'] } });
  const a = compose(dir, 'app/en/page.tsx', 'hero');
  assert.match(a.chrome || '', /layout|--chrome/);
  const b = compose(dir, 'app/en/contact/page.tsx', 'hero', ['--chrome', 'yes']);
  assert.deepEqual(b.sections.map((s) => s.slot), ['navbar', 'hero', 'footer']);
});

test('seo apply on a path-prefixed i18n site writes hreflang alternates per page and in the sitemap, and says what stays manual', () => {
  const dir = scratch('dh-seo-i18n-');
  const wr = (f, t) => { fs.mkdirSync(path.dirname(path.join(dir, f)), { recursive: true }); fs.writeFileSync(path.join(dir, f), t); };
  wr('package.json', JSON.stringify({ name: 'nour', dependencies: { next: '16.3.6', react: '19.0.0' } }));
  wr('tsconfig.json', JSON.stringify({ compilerOptions: { paths: { '@/*': ['./*'] } } }));
  wr('app/layout.tsx', 'export default function RootLayout({ children }: { children: React.ReactNode }) {\n  return (\n    <html lang="fr">\n      <body>{children}</body>\n    </html>\n  );\n}\n');
  wr('app/page.tsx', 'export default function Home() {\n  return <h1>Accueil</h1>;\n}\n');
  wr('app/en/page.tsx', 'export default function Home() {\n  return <h1>Home</h1>;\n}\n');
  const alt = { fr: '/', en: '/en', 'x-default': '/' };
  const plan = { site: { name: 'Nour', url: 'https://nour.example', languages: ['fr', 'en'], locale: 'fr_FR' }, jsonld: { '@context': 'https://schema.org' }, i18n: 'prefix',
    pages: [{ route: '/', alternates: alt }, { route: '/en', alternates: alt }] };
  const r = seoApply(dir, plan);
  assert.match(read(dir, 'app/page.tsx'), /languages:\s*\{[^}]*"en":\s*"\/en"/);
  assert.match(read(dir, 'app/en/page.tsx'), /"x-default":\s*"\/"/);
  assert.match(read(dir, 'app/sitemap.ts'), /alternates/);
  assert.ok(r.say && r.say.some((s) => /manual edit/.test(s) && /lang/.test(s)), 'lang is reported honestly');
});
