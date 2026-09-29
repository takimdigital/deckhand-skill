#!/usr/bin/env node
/**
 * tryon — Deckhand's live component swap. One JSON object per command on stdout; exit 0 = ok.
 *
 *   node tryon/cli.mjs setup    [--project .]                      wire the dev-only stamp (restart dev)
 *   node tryon/cli.mjs serve    [--project .] [--port 3999] [--target http://127.0.0.1:3000]
 *   node tryon/cli.mjs doctor   [--project .]                      is everything wired? (no writes)
 *   node tryon/cli.mjs slots    [--project .]                      what can be tried here
 *   node tryon/cli.mjs query    --slot hero [--project .]          ranked candidates (no writes)
 *   node tryon/cli.mjs inspect  --file f --line n --col c [--slot s]
 *   node tryon/cli.mjs try      --file f --line n --col c --slot s [--count 4] [--no-install] [--registry r] [--only id,id]
 *   node tryon/cli.mjs more     --id S [--batch 4]                 the next designs from the pool, after the ones shown
 *   node tryon/cli.mjs show     --id S --idx N                     make variant N the visible one
 *   node tryon/cli.mjs keep     --id S [--idx N]                   collapse to N, bake the text, graduate
 *   node tryon/cli.mjs discard  --id S                             byte-exact restore
 *   node tryon/cli.mjs save     --id S [--name n]                  kept component -> personal library
 *   node tryon/cli.mjs status   [--project .]
 *   node tryon/cli.mjs clean    [--project .]                      discard open sessions, unwire
 *
 * AI draft (no licensed design fits, or the owner asks) — the agent writes ONE variant, scripts gate it:
 *   node tryon/cli.mjs draft      --file f --line n --col c --slot s [--note "…"]  |  --session S
 *   node tryon/cli.mjs drafts     [--wait [--timeout 1800]]          pending requests (+ each brief path)
 *   node tryon/cli.mjs draft-check --id D                            run the gates, write nothing
 *   node tryon/cli.mjs draft-done  --id D                            gate + show it (labelled AI-generated)
 *
 * Tune one element / the whole Site without a browser (same engine as the overlay; deterministic, reversible):
 *   node tryon/cli.mjs tune  --file f --line n --col c [--preset quieter] [--density 1 --size -1 --corners round …]
 *   node tryon/cli.mjs tune  --id T --keep | --reset          (an open tune: --id T with new dials re-applies)
 *   node tryon/cli.mjs theme                                  current knobs, choices, fonts
 *   node tryon/cli.mjs theme --accent teal --neutrals warm --corners soft --density airy --headlines larger --body Inter --heading Fraunces
 *   node tryon/cli.mjs theme --undo [--force]                 byte-exact restore of the last apply (refused if edited since)
 *
 * SEO (driven by `dh seo`, which builds the plan from the brief's confirmed facts):
 *   node tryon/cli.mjs seo inspect | seo apply --plan plan.json | seo undo
 *
 * Flags (a variant that does not work, flagged from the try-on bar) and the report an AI can fix the engine from:
 *   node tryon/cli.mjs flags list | flags report [--ids F1a2b3c4d,…] | flags remove --id F… | flags clear
 *
 * A registry someone found — vetted (licence, paywall, schema, usable items) before it is indexed, then fit-checked:
 *   node tryon/cli.mjs registry vet|add --index https://…/registry.json --repo owner/name [--id x]
 *   node tryon/cli.mjs registry list | registry remove --id x
 *   node tryon/cli.mjs registry check --id x [--sample N] [--md] [--ship]   stage each design against an owner section
 *     of its kind: fits | partial | refused | broken (hidden) | unreachable | unchecked (--id all: every registry)
 */
import fs from 'node:fs';
import path from 'node:path';
import * as engine from './lib/engine.mjs';
import { setup, unsetup, readJournal } from './lib/setup.mjs';
import { detectProject } from './lib/project.mjs';
import { loadCatalog, rank, slotsSummary } from './lib/catalog.mjs';
import { saveToLibrary, listLibrary } from './lib/library.mjs';
import { startServer, detectTarget } from './server.mjs';
import * as draft from './lib/draft.mjs';
import { vetRegistry, addRegistry, listRegistries, removeRegistry } from './lib/vet.mjs';
import { fitCheck, fitMarkdown, recordVerdicts, shippedChecksDir, localChecksDir } from './lib/fitcheck.mjs';
import { tuneOpen, tuneSet, tuneKeep, tuneReset, DIALS, PRESETS } from './lib/tune.mjs';
import { themeState, themeApply, themeUndo } from './lib/sitetheme.mjs';
import { seoInspect, seoApply, seoUndo } from './lib/seo.mjs';
import { REASONS, listFlags, publicFlag, removeFlag, clearFlags, buildReport } from './lib/flags.mjs';

const argv = process.argv.slice(2);
const cmd = argv[0];
const flags = {};
const words = [];                                   // sub-actions (`flags list`), wherever they sit among the options
for (let i = 1; i < argv.length; i++) {
  const a = argv[i];
  if (!a.startsWith('--')) { words.push(a); continue; }
  const k = a.slice(2);
  if (k.startsWith('no-')) { flags[k.slice(3)] = false; continue; }
  const v = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : true;
  flags[k] = v;
}
const project = path.resolve(String(flags.project || '.'));
const out = (o, code = 0) => { process.stdout.write(JSON.stringify(o) + '\n'); process.exit(code); };
const need = (...ks) => { const miss = ks.filter((k) => flags[k] === undefined || flags[k] === true); if (miss.length) out({ ok: false, code: 'USAGE', missing: miss.map((m) => '--' + m) }, 2); };

/** `registry check`: stage each design (or a sample) against an owner section of its kind; record the verdicts. */
async function checkRegistries(id, { sample = 0, md = false, ship = false } = {}) {
  const items = loadCatalog();
  const ids = id === 'all' ? [...new Set(items.map((x) => x.r))].filter((r) => r !== 'mine').sort() : [id];
  const registries = [];
  for (const r of ids) {
    const mine = items.filter((x) => x.r === r);
    if (!mine.length) throw Object.assign(new Error(`no designs from a registry "${r}" (registry list / query --slot …)`), { code: 'NO_SUCH_REGISTRY' });
    const res = await fitCheck({ id: r, items: mine, sample, onProgress: (p) => { if (process.stderr.isTTY) process.stderr.write(`\r${r} ${p.done}/${p.of}`); } });
    const rec = recordVerdicts(res, { dir: ship ? shippedChecksDir() : localChecksDir() });
    const row = { registry: r, checked: res.checked, of: res.of, counts: res.counts, verdicts: rec.file };
    if (md) { const f = rec.file.replace(/\.json$/, '.md'); fs.writeFileSync(f, fitMarkdown(res)); row.report = f; }
    registries.push(row);
  }
  if (process.stderr.isTTY) process.stderr.write('\n');
  return { registries, next: 'broken designs are no longer offered; refused ones come last. `--md` writes the per-design reasons' };
}

async function main() {
  switch (cmd) {
    case 'setup': return out(setup(project));
    case 'serve': {
      const target = flags.target || await detectTarget(project);
      if (!target) out({ ok: false, code: 'NO_DEV_SERVER', hint: 'start the dev server first (npm run dev), or pass --target http://127.0.0.1:<port>' }, 1);
      const port = Number(flags.port || 3999);
      // a port already taken is often an older try-on server, maybe for another project: its overlay keeps answering
      const s = await startServer({ root: project, port, target, log: flags.verbose ? (e) => console.error(JSON.stringify(e)) : () => {},
        onDraft: (r) => process.stdout.write(JSON.stringify({ event: 'draft_request', id: r.id, slot: r.slot, brief_file: r.brief_file, do: r.tell_agent }) + '\n') })
        .catch((e) => { if (e.code !== 'EADDRINUSE') throw e;
          return out({ ok: false, code: 'PORT_BUSY', port, message: `port ${port} is already in use, often by an older try-on server (it may be showing another project): stop it, or pass --port <free port>` }, 1); });
      process.stdout.write(JSON.stringify({ ok: true, open: s.url, proxying: target, note: 'open the URL, click Try-on (bottom right). Ctrl+C stops.' }) + '\n');
      return;
    }
    case 'doctor': {
      const prof = detectProject(project);
      const j = readJournal(project);
      const target = flags.target || await detectTarget(project);
      let stamped = null;
      if (target) {
        try {
          const html = await (await fetch(target + (flags.path || '/'))).text();
          stamped = /data-dh="/.test(html);
          // a Vite page renders in the browser: the stamps live in the modules it loads, not in the HTML
          const entry = !stamped && prof.framework === 'vite' ? /<script[^>]+type="module"[^>]+src="(\/(?!@)[^"]+)"/.exec(html) : null;
          if (entry) stamped = /data-dh(=\\?"|":)/.test(await (await fetch(target + entry[1])).text());
        } catch { stamped = false; }
      }
      const checks = {
        framework: prof.framework, supported: ['next', 'vite'].includes(prof.framework), wired: !!j, devServer: target || null,
        stampsInHtml: stamped, tailwind: prof.tailwind, tokens: prof.tokens, base: prof.base, globalsCss: prof.globalsCss,
      };
      const next = !checks.supported ? 'degraded mode: use `try` with --file/--line/--col' : !j ? 'run `setup`, then restart the dev server'
        : !target ? 'start the dev server' : stamped === false ? 'restart the dev server so the stamp loader loads' : 'run `serve` and open its URL';
      return out({ ok: true, ...checks, next });
    }
    case 'slots': {
      const prof = detectProject(project);
      return out({ ok: true, base: prof.base, slots: slotsSummary(loadCatalog(), prof) });
    }
    case 'query': {
      need('slot');
      const prof = detectProject(project);
      const r = rank(loadCatalog(), { slot: flags.slot, prof, registry: flags.registry || null });
      return out({ ok: true, slot: flags.slot, hidden: r.hidden, total: r.items.length,
        top: r.items.slice(0, Number(flags.top || 8)).map((x) => ({ id: x.id, t: x.t, score: x.score, missing: x.missing })) });
    }
    case 'inspect': need('file', 'line', 'col'); return out({ ok: true, ...engine.inspect(project, flags) });
    case 'try': {
      need('file', 'line', 'col', 'slot');
      // with a running dev server (--url, else the one `dh dev start` recorded) the page must still build after the swap
      let devUrl = typeof flags.url === 'string' ? flags.url : null;
      if (!devUrl && flags.verify !== false) { try { devUrl = JSON.parse(fs.readFileSync(path.join(project, '.deckhand', 'dev.json'), 'utf8')).url || null; } catch { devUrl = null; } }
      const r = await engine.openVerified(project, { ...flags, only: typeof flags.only === 'string' ? flags.only : undefined, install: flags.install !== false, onProgress: flags.verbose ? (p) => console.error(JSON.stringify(p)) : undefined },
        { url: devUrl, page: typeof flags.page === 'string' ? flags.page : '/' });
      return out({ ok: true, ...r, next: `compare in the browser (←/→) or \`show --id ${r.id} --idx N\`; then \`keep --id ${r.id} --idx N\` or \`discard --id ${r.id}\`` });
    }
    case 'more': {
      need('id');
      let devUrl = typeof flags.url === 'string' ? flags.url : null;
      if (!devUrl && flags.verify !== false) { try { devUrl = JSON.parse(fs.readFileSync(path.join(project, '.deckhand', 'dev.json'), 'utf8')).url || null; } catch { devUrl = null; } }
      const r = await engine.more(project, flags.id, { batch: flags.batch, url: devUrl, page: typeof flags.page === 'string' ? flags.page : '/',
        onProgress: flags.verbose ? (p) => console.error(JSON.stringify(p)) : undefined });
      return out({ ok: true, ...r, next: r.added ? `variants ${r.startAt}–${r.variants.length - 1} are new; compare, then keep or discard` : 'no new design could be staged; keep or discard' });
    }
    case 'draft': {
      if (!flags.session) need('file', 'line', 'col', 'slot');
      const r = draft.requestDraft(project, { ...flags, note: typeof flags.note === 'string' ? flags.note : null });
      const d = draft.loadDraft(project, r.id);
      return out({ ok: true, ...r, brief: d.brief });
    }
    case 'drafts': {
      // --wait: ONE blocking call for harnesses that can run it in the background (no polling by the model)
      const t0 = Date.now(), limit = Number(flags.timeout || 1800) * 1000;
      let pending = draft.listDrafts(project, { state: ['pending', 'rejected'] });
      while (flags.wait && !pending.length && Date.now() - t0 < limit) {
        await new Promise((r) => setTimeout(r, 1500));
        pending = draft.listDrafts(project, { state: ['pending', 'rejected'] });
      }
      return out({ ok: true, pending: pending.map((d) => ({ ...draft.publicDraft(d), brief_file: path.posix.join('.deckhand/tryon/drafts', d.id + '.json') })),
        next: pending.length ? 'read the brief_file "brief", write the component into write_to, run `then`' : 'no request — the owner asks from the try-on panel ("Ask AI to draft one")' });
    }
    case 'draft-check': { need('id'); const r = draft.checkDraft(project, flags.id); return out(r, r.ok ? 0 : 1); }
    case 'draft-done': {
      need('id');
      const r = await draft.completeDraft(project, flags.id, { install: false });
      return out({ ok: true, ...r, next: `the owner compares it in the browser (labelled AI-generated) — or \`show --id ${r.id} --idx ${r.ai_variant}\`, then keep/discard` });
    }
    case 'flags': {
      const act = words[0] || 'list';
      if (act === 'list') return out({ ok: true, flags: listFlags(project).map(publicFlag), reasons: REASONS });
      if (act === 'remove') { need('id'); return out({ ok: true, ...removeFlag(project, flags.id) }); }
      if (act === 'clear') return out({ ok: true, ...clearFlags(project) });
      if (act === 'report') {
        const r = buildReport(project, typeof flags.ids === 'string' ? flags.ids.split(',').map((x) => x.trim()).filter(Boolean) : null);
        return out({ ok: true, path: r.path, flags: r.flags, bytes: Buffer.byteLength(r.markdown),
          next: 'give this file to the AI improving try-on (it holds the site owner\'s text: send it, never publish it)' });
      }
      return out({ ok: false, code: 'USAGE', usage: 'flags list | flags report [--ids a,b] | flags remove --id F… | flags clear' }, 2);
    }
    case 'registry': {
      // a registry the owner (or the agent) found: vetted against written criteria before anything is indexed
      const act = words[0];
      if (act === 'list') return out({ ok: true, registries: listRegistries() });
      if (act === 'remove') { need('id'); return out({ ok: true, ...removeRegistry(flags.id) }); }
      if (act === 'check') { need('id'); return out({ ok: true, ...(await checkRegistries(String(flags.id), { sample: Number(flags.sample) || 0, md: !!flags.md, ship: !!flags.ship })) }); }
      if (!['vet', 'add'].includes(act)) return out({ ok: false, code: 'USAGE', usage: 'registry vet|add --index https://…/registry.json --repo owner/name [--id x] | registry list | registry remove --id x | registry check --id x|all [--sample N] [--md]' }, 2);
      need('index');
      const o = { index: flags.index, repo: typeof flags.repo === 'string' ? flags.repo : null, id: typeof flags.id === 'string' ? flags.id : null, item: typeof flags.item === 'string' ? flags.item : null };
      if (act === 'vet') { const { _reg, _items, ...v } = await vetRegistry(o); return out({ ok: v.verdict === 'accepted', ...v }, v.verdict === 'accepted' ? 0 : 1); }
      const added = await addRegistry(o);
      // a registry that is added is fit-checked at once (a sample): the owner is never offered what cannot be staged
      const fit = await checkRegistries(added.registry, { sample: Number(flags.sample) || 8 });
      return out({ ok: true, ...added, fit: fit.registries[0] });
    }
    case 'tune': {
      const dials = Object.fromEntries(Object.keys(DIALS).filter((k) => flags[k] !== undefined && flags[k] !== true).map((k) => [k, flags[k]]));
      const preset = typeof flags.preset === 'string' ? flags.preset : null;
      if (flags.id) {
        if (flags.keep) return out({ ok: true, ...tuneKeep(project, flags.id) });
        if (flags.reset) return out({ ok: true, ...tuneReset(project, flags.id) });
        return out({ ok: true, ...tuneSet(project, flags.id, { dials, preset }) });
      }
      need('file', 'line', 'col');
      if (!preset && !Object.keys(dials).length) return out({ ok: false, code: 'USAGE', dials: DIALS, presets: Object.keys(PRESETS) }, 2);
      const t = tuneOpen(project, flags);
      const r = tuneSet(project, t.id, { dials, preset });
      return out({ ok: true, ...r, file: t.file, next: `look at it (HMR); then \`tune --id ${t.id} --keep\` or \`--reset\` (byte-exact)` });
    }
    case 'theme': {
      if (flags.undo) return out({ ok: true, ...themeUndo(project, { force: !!flags.force }) });
      const knobs = Object.fromEntries(['accent', 'neutrals', 'corners', 'density', 'headlines', 'body', 'heading']
        .filter((k) => typeof flags[k] === 'string').map((k) => [k, flags[k]]));
      if (!Object.keys(knobs).length) return out({ ok: true, ...themeState(project) });
      return out({ ok: true, ...themeApply(project, knobs), next: 'restart not needed (HMR); `theme --undo` restores the previous files byte-exact' });
    }
    case 'seo': {
      const act = words[0];
      if (act === 'inspect') return out({ ok: true, ...seoInspect(project) });
      if (act === 'undo') return out({ ok: true, ...seoUndo(project, { force: !!flags.force }) });
      if (act === 'apply') { need('plan'); return out({ ok: true, ...seoApply(project, JSON.parse(fs.readFileSync(path.resolve(String(flags.plan)), 'utf8'))) }); }
      return out({ ok: false, code: 'USAGE', usage: 'seo inspect | seo apply --plan plan.json | seo undo (usually through `dh seo`)' }, 2);
    }
    case 'show': need('id', 'idx'); return out({ ok: true, ...engine.show(project, flags.id, flags.idx) });
    case 'keep': need('id'); return out(engine.keep(project, flags.id, flags.idx));
    case 'discard': need('id'); return out(engine.discard(project, flags.id));
    case 'save': need('id'); return out({ ok: true, ...saveToLibrary(project, flags.id, { name: flags.name }) });
    case 'library': return out({ ok: true, items: listLibrary().map((i) => ({ id: i.id, slot: i.slot, t: i.t })) });
    case 'status': {
      const ss = engine.listSessions(project);
      return out({ ok: true, wired: !!readJournal(project), open: ss.filter((s) => s.state === 'open').map(engine.publicSession),
        kept: ss.filter((s) => s.state === 'kept').map((s) => ({ id: s.id, file: s.file, component: s.final?.entry })) });
    }
    case 'clean': {
      const ss = engine.listSessions(project);
      const discarded = ss.filter((s) => s.state === 'open').map((s) => engine.discard(project, s.id).id);
      const kept = ss.some((s) => s.state === 'kept');
      const r = unsetup(project, { keepTokens: kept ? true : false });
      if (!kept) { try { fs.unlinkSync(path.join(project, 'public', 'deckhand-placeholder.svg')); } catch { /* none */ } }
      return out({ ok: true, discarded, ...r, restartDevServer: true });
    }
    default:
      return out({ ok: false, code: 'USAGE', commands: ['setup', 'serve', 'doctor', 'slots', 'query', 'inspect', 'try', 'more', 'show', 'keep', 'discard', 'save', 'library', 'status', 'clean', 'draft', 'drafts', 'draft-check', 'draft-done', 'tune', 'theme', 'seo', 'flags', 'registry'] }, 2);
  }
}

main().catch((e) => out({ ok: false, code: e.code || 'ERROR', message: String(e.message || e).slice(0, 3000), skipped: e.skipped, problems: e.problems, ...(e.report ? { report: e.report } : {}),
  ...(e.reload ? { reload: true, next: 'the page is older than the file: reload it (or re-run inspect) and pick again' } : {}),
  ...(e.restored ? { restored: true } : {}), ...(e.pool ? { pool: e.pool } : {}), ...(e.dropped && e.dropped.length ? { dropped: e.dropped } : {}),
  ...(e.installedKept && e.installedKept.length ? { installedKept: e.installedKept } : {}),
  ...(e.draft ? { next: `no licensed design fits — an AI draft is possible (labelled AI-generated for the owner): draft --file ${e.draft.file} --line ${e.draft.line} --col ${e.draft.col} --slot ${e.draft.slot}` } : {}) }, 1));
