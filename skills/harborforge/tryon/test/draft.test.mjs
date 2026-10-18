import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { tempSite, offline, read, locate } from './helpers.mjs';
import * as engine from '../lib/engine.mjs';
import * as draft from '../lib/draft.mjs';

const require = createRequire(import.meta.url);
const { parse } = require('../lib/ast.cjs');
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');

offline();

/** What a good agent writes: the owner's words and links, token colours, the placeholder, one AI-written line. */
const GOOD = `import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function HeroDraft() {
  return (
    <section className="bg-muted/40 px-6 py-20">
      <div className="mx-auto grid max-w-5xl gap-10 md:grid-cols-2 md:items-center">
        <div>
          <h1 className="text-4xl font-semibold tracking-tight text-foreground md:text-6xl">
            Sourdough delivered <span className="text-primary">warm</span> to your door
          </h1>
          <p className="mt-5 text-lg text-muted-foreground">Maison Levain bakes every loaf at 4am and delivers across Lyon before breakfast.</p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Button asChild size="lg"><Link href="/order">Order your first loaf</Link></Button>
            <Button asChild size="lg" variant="outline"><Link href="#menu">See the menu</Link></Button>
          </div>
        </div>
        <img src="/deckhand-placeholder.svg" alt="Bread on a table" className="aspect-[4/3] w-full rounded-xl border border-border object-cover" />
      </div>
      <p className="mt-6 text-center text-sm text-muted-foreground">Fresh every morning</p>
    </section>
  );
}
`;

function heroRequest(dir, extra = {}) {
  const at = locate(read(dir, 'components/hero.tsx'), '<section');
  return draft.requestDraft(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', ...extra });
}
const writeDraft = (dir, r, code, name = 'draft.tsx') => fs.writeFileSync(path.join(dir, r.write_to, name), code);

test('request -> a brief with the owner content, the project and the rules; nothing is written to source', () => {
  const dir = tempSite();
  const before = fs.readFileSync(path.join(dir, 'components/hero.tsx'));
  const r = heroRequest(dir, { note: 'image on the right' });
  assert.equal(r.state, 'pending');
  assert.match(r.then, /draft-done --project ".+" --id d/);
  const b = draft.loadDraft(dir, r.id).brief;
  assert.deepEqual(b.content.units.map((u) => u.role), ['heading', 'text', 'action', 'action']);
  assert.match(b.content.units[0].markup, /<span className="text-amber-600">warm<\/span>/);
  assert.deepEqual(b.content.units.slice(2).map((u) => u.href), ['/order', '#menu']);
  assert.equal(b.project.ui.button, '@/components/ui/button');
  assert.equal(b.owner_note, 'image on the right');
  assert.ok(b.rules.some((x) => /Invent no facts/.test(x)) && b.rules.some((x) => /token classes only/.test(x)));
  assert.equal(sha(fs.readFileSync(path.join(dir, 'components/hero.tsx'))), sha(before));
  assert.deepEqual(draft.checkDraft(dir, r.id).problems.map((p) => p.code), ['DRAFT_EMPTY']);
});

test('a gated draft appears labelled AI-generated, carries every owner unit, and keep records provenance, not a licence', async () => {
  const dir = tempSite();
  const r = heroRequest(dir);
  writeDraft(dir, r, GOOD);
  const s = await draft.completeDraft(dir, r.id);
  assert.equal(s.variants.length, 2);
  const v = s.variants[1];
  assert.equal(v.generated, true);
  assert.equal(v.t, 'AI draft · hero');
  assert.equal(v.lic, 'AI-generated');
  assert.equal(v.fit.carried, 4);
  assert.equal(v.fit.of, 4);
  assert.deepEqual(s.ai_copy, ['Fresh every morning']);
  assert.ok(v.fit.demo.some((t) => /Fresh every morning/.test(t)));
  const hero = read(dir, 'components/hero.tsx');
  parse('hero.tsx', hero);
  assert.match(hero, /data-dh-label="AI draft · hero"/);
  const staged = read(dir, `components/dh-tryon/ai-hero-draft-${r.id}/ai-hero-draft-${r.id}.tsx`);
  assert.match(staged, /^\/\* AI-generated — AI draft · hero/);
  assert.doesNotMatch(staged, /\(MIT\)/);
  assert.equal(draft.loadDraft(dir, r.id).state, 'done');

  const k = engine.keep(dir, s.id, v.idx);
  assert.equal(k.generated, true);
  assert.equal(k.local, 'HeroAiDraft');
  assert.deepEqual(k.demo_copy_to_replace, ['Fresh every morning']);
  const comp = read(dir, k.component);
  assert.match(comp, /^\/\* AI-generated — /);
  assert.match(comp, /Sourdough delivered <span className="text-primary">warm<\/span> to your door/);
  assert.ok(!fs.existsSync(path.join(dir, 'THIRD_PARTY_NOTICES.md')) || !/ai-hero-draft/.test(read(dir, 'THIRD_PARTY_NOTICES.md')));
  const ledger = JSON.parse(read(dir, '.deckhand/demo-copy.json')).entries;
  assert.deepEqual(ledger.map((e) => [e.text, e.ai]), [['Fresh every morning', true]]);
});

test('one rejection lists every problem: a link the owner never gave AND the words it dropped (was one round each)', async () => {
  const dir = tempSite();
  const r = heroRequest(dir);
  writeDraft(dir, r, GOOD.replace('<Button asChild size="lg" variant="outline"><Link href="#menu">See the menu</Link></Button>', '<a href="/nope">x</a>'));
  await assert.rejects(draft.completeDraft(dir, r.id), (e) => {
    assert.deepEqual(e.problems.map((p) => p.code).sort(), ['DRAFT_DROPPED_CONTENT', 'DRAFT_LINK']);
    return true;
  });
});

test('the gates reject what an unsupervised model gets wrong — and the page is untouched', async () => {
  const dir = tempSite();
  const before = fs.readFileSync(path.join(dir, 'components/hero.tsx'));
  const r = heroRequest(dir);
  writeDraft(dir, r, GOOD
    .replace('import Link from "next/link";', 'import Link from "next/link";\nimport { motion } from "framer-motion";')
    .replace('bg-muted/40', 'bg-[#f5e6d3]')
    .replace('/deckhand-placeholder.svg', 'https://images.unsplash.com/photo-1.jpg')
    .replace('<p className="mt-6', '<a href="/pricing">Pricing</a><p className="mt-6')
    .replace('return (', 'fetch("/api/x");\n  return ('));
  fs.writeFileSync(path.join(dir, r.write_to, 'styles.css'), '.x{color:red}');
  await assert.rejects(draft.completeDraft(dir, r.id), (e) => {
    assert.equal(e.code, 'DRAFT_REJECTED');
    assert.deepEqual([...new Set(e.problems.map((p) => p.code))].sort(),
      ['DRAFT_FILE', 'DRAFT_IMAGE', 'DRAFT_IMPORT', 'DRAFT_LINK', 'DRAFT_RAW_COLOR', 'DRAFT_SIDE_EFFECT']);
    return true;
  });
  assert.equal(draft.loadDraft(dir, r.id).state, 'rejected');
  assert.equal(sha(fs.readFileSync(path.join(dir, 'components/hero.tsx'))), sha(before));
  // the agent fixes it; a dropped owner line or link is still refused, by name
  fs.rmSync(path.join(dir, r.write_to, 'styles.css'));
  writeDraft(dir, r, GOOD.replace('<Button asChild size="lg" variant="outline"><Link href="#menu">See the menu</Link></Button>', ''));
  await assert.rejects(draft.completeDraft(dir, r.id), (e) => {
    assert.deepEqual(e.problems.map((p) => p.detail), ['missing action: "See the menu"']);
    return true;
  });
  // the words kept but the link changed is refused too (the owner's CTA must still go where it went)
  writeDraft(dir, r, GOOD.replace('<Link href="#menu">See the menu</Link>', '<Link href="/order">See the menu</Link>'));
  await assert.rejects(draft.completeDraft(dir, r.id), (e) => {
    assert.deepEqual(e.problems.map((p) => p.detail), ['missing action: "See the menu (link #menu)"']);
    return true;
  });
  writeDraft(dir, r, GOOD);
  const s = await draft.completeDraft(dir, r.id);
  assert.equal(s.variants[1].generated, true);
});

test('asked from an open session: the AI draft joins the licensed variants the owner was comparing', async () => {
  const dir = tempSite();
  const at = locate(read(dir, 'components/hero.tsx'), '<section');
  const s0 = await engine.open(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', count: 2, registry: 'tailark-oss', install: false });
  const r = draft.requestDraft(dir, { session: s0.id });
  assert.deepEqual(draft.loadDraft(dir, r.id).brief.content.units.map((u) => u.role), ['heading', 'text', 'action', 'action']);
  writeDraft(dir, r, GOOD);
  const s = await draft.completeDraft(dir, r.id);
  assert.equal(engine.loadSession(dir, s0.id).state, 'discarded');
  assert.equal(s.variants.length, 4);                                        // original + AI + the 2 licensed
  assert.equal(s.variants.filter((v) => v.generated).length, 1);
  assert.deepEqual(s.variants.filter((v) => !v.generated && v.idx).map((v) => v.id).sort(), s0.variants.slice(1).map((v) => v.id).sort());
  parse('hero.tsx', read(dir, 'components/hero.tsx'));
  engine.discard(dir, s.id);
});

test('variants opened on the element while the agent was writing are folded in, never wrapped twice', async () => {
  const dir = tempSite();
  const r = heroRequest(dir);                                                 // asked from the panel (no session)
  const at = locate(read(dir, 'components/hero.tsx'), '<section');
  const s0 = await engine.open(dir, { file: 'components/hero.tsx', ...at, slot: 'hero', count: 2, registry: 'tailark-oss', install: false });
  writeDraft(dir, r, GOOD);
  const s = await draft.completeDraft(dir, r.id);
  assert.equal(engine.loadSession(dir, s0.id).state, 'discarded');
  assert.equal(s.variants.length, 4);
  const hero = read(dir, 'components/hero.tsx');
  assert.equal((hero.match(/data-dh-session=/g) || []).length, 1);
  parse('hero.tsx', hero);
});

test('no licensed candidate -> the error says an AI draft is possible, with the exact element', async () => {
  const dir = tempSite();
  const at = locate(read(dir, 'components/hero.tsx'), '<section');
  await assert.rejects(engine.open(dir, { file: 'components/hero.tsx', ...at, slot: 'blog', install: false }), (e) => {
    assert.equal(e.code, 'NO_CANDIDATES');
    assert.deepEqual(e.draft, { file: 'components/hero.tsx', ...at, slot: 'blog' });
    return true;
  });
});
