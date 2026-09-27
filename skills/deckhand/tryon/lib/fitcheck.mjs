/**
 * fitcheck.mjs — does a registry's design fit before an owner is ever offered it?
 *
 * Every design is staged exactly the way a try stages it (engine.stageCandidate: fetched, themed, the owner's
 * content transplanted, fit-gated) against an owner section of its kind, in a throwaway site shaped like a Deckhand
 * scaffold (Next + Tailwind 4 + the radix-ui umbrella + Button, or the Base UI equivalent). One verdict each:
 *   fits        offered, and every owner word is carried
 *   partial     offered, but some owner words are dropped (listed)
 *   refused     the fit gate would never offer it for that kind of section (POOR_FIT)
 *   broken      the engine cannot stage it (UNRESOLVED_IMPORT, NO_EXPORT, PARAMETERIZE_FAILED): an engine gap
 *               to fix, hidden from the owner until then
 *   unreachable its files could not be downloaded: no verdict
 *   unchecked   no owner section of its kind (effects, charts, app widgets)
 * `needs` lists the packages a real project would install first (open() prefers designs that need none).
 * Offline by design: no dev server, no install, imports are not resolved — a try still checks them before wiring.
 * Verdicts: shipped in data/checks/<registry>.json, the owner's own runs in ~/.deckhand/catalog/checks/ (they win);
 * rank() hides broken designs and puts refused ones last.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { detectProject } from './project.mjs';
import { SKILL_DIR, localChecksDir } from './catalog.mjs';
export { shippedChecksDir, localChecksDir, loadVerdicts } from './catalog.mjs';
import { stagingContext, stageCandidate } from './engine.mjs';

const require = createRequire(import.meta.url);
const { parse, findElementAt } = require('./ast.cjs');

export const VERDICTS = ['fits', 'partial', 'refused', 'broken', 'unreachable', 'unchecked'];
const BROKEN = new Set(['UNRESOLVED_IMPORT', 'NO_EXPORT', 'PARAMETERIZE_FAILED']);

/* ------------------------------------------------------------------ the owner's sections (one per kind) */

const LINK = 'import Link from "next/link";\n';
const BTN = 'import { Button } from "@/components/ui/button";\n';

/** slot -> { code, at }: `at` is the text the owner's element starts with (the element the owner would click). */
export const REFERENCE = {
  hero: { at: '<section', code: LINK + BTN + `
export function Hero() {
  return (
    <section className="mx-auto max-w-3xl px-6 py-24 text-center">
      <h1 className="text-5xl font-bold tracking-tight">Sourdough delivered warm to your door</h1>
      <p className="mt-6 text-lg text-muted-foreground">Maison Levain bakes every loaf at 4am and delivers across Lyon before breakfast.</p>
      <div className="mt-10 flex justify-center gap-4">
        <Button asChild size="lg"><Link href="/order">Order your first loaf</Link></Button>
        <Button asChild size="lg" variant="outline"><Link href="/menu">See the menu</Link></Button>
      </div>
    </section>
  );
}
` },
  features: { at: '<section', code: `const perks = [
  { title: "Baked at 4am", text: "Every loaf leaves the oven less than three hours before it reaches you." },
  { title: "Organic flour", text: "Stone-milled wheat and rye from two farms in the Rhône valley." },
  { title: "Free delivery", text: "Anywhere in Lyon for orders over 15 euros, before 8am." },
];
export function Features() {
  return (
    <section className="py-20">
      <h2 className="text-3xl font-semibold">Why Maison Levain</h2>
      <p className="mt-3 text-muted-foreground">Real bread, made the slow way, on your table every morning.</p>
      <div className="mt-10 grid gap-8 md:grid-cols-3">
        {perks.map((p) => (
          <div key={p.title}>
            <h3 className="font-semibold">{p.title}</h3>
            <p className="mt-2 text-sm text-muted-foreground">{p.text}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
` },
  content: { at: '<section', code: LINK + `
export function Story() {
  return (
    <section className="py-20">
      <h2 className="text-3xl font-semibold">Our story</h2>
      <p className="mt-4 text-muted-foreground">Claire opened Maison Levain in 2014 with one wood oven and a starter from her grandmother.</p>
      <p className="mt-4 text-muted-foreground">Ten years later we still shape every loaf by hand and bake nothing we would not eat ourselves.</p>
      <img src="/deckhand-placeholder.svg" alt="Claire shaping loaves" className="mt-8 rounded-xl" />
      <Link href="/about" className="mt-6 inline-block underline">Meet the bakers</Link>
    </section>
  );
}
` },
  pricing: { at: '<section', code: LINK + `
export function Pricing() {
  return (
    <section className="py-20">
      <h2 className="text-3xl font-semibold">Bread subscriptions</h2>
      <p className="mt-3 text-muted-foreground">Pause or cancel any week.</p>
      <div className="mt-10 grid gap-6 md:grid-cols-2">
        <div className="rounded-xl border p-6">
          <h3 className="font-semibold">Weekly loaf</h3>
          <p className="mt-2 text-3xl font-bold">€12 / week</p>
          <ul className="mt-4 space-y-2 text-sm"><li>One sourdough every Saturday</li><li>Free delivery</li></ul>
          <Link href="/order?plan=weekly" className="mt-6 inline-block rounded-md bg-primary px-4 py-2 text-primary-foreground">Subscribe</Link>
        </div>
        <div className="rounded-xl border p-6">
          <h3 className="font-semibold">Family box</h3>
          <p className="mt-2 text-3xl font-bold">€29 / week</p>
          <ul className="mt-4 space-y-2 text-sm"><li>Three loaves and a brioche</li><li>Choose your days</li></ul>
          <Link href="/order?plan=family" className="mt-6 inline-block rounded-md bg-primary px-4 py-2 text-primary-foreground">Subscribe</Link>
        </div>
      </div>
    </section>
  );
}
` },
  testimonials: { at: '<section', code: `const quotes = [
  { quote: "The best sourdough in Lyon, and it arrives before my coffee is ready.", name: "Sophie M.", role: "Croix-Rousse" },
  { quote: "Our café switched to Maison Levain and customers noticed the same week.", name: "Hugo D.", role: "Café Pistache" },
];
export function Testimonials() {
  return (
    <section className="py-20">
      <h2 className="text-3xl font-semibold">What our neighbours say</h2>
      <div className="mt-10 grid gap-8 md:grid-cols-2">
        {quotes.map((q) => (
          <figure key={q.name} className="rounded-xl border p-6">
            <blockquote className="text-lg">{q.quote}</blockquote>
            <figcaption className="mt-4 text-sm"><span className="font-semibold">{q.name}</span> · {q.role}</figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}
` },
  faq: { at: '<section', code: `const faqs = [
  { q: "When do you deliver?", a: "Every morning between 6 and 8am, Tuesday to Sunday." },
  { q: "Can I pause my subscription?", a: "Yes, any week, from your account, until Thursday midnight." },
  { q: "Do you bake gluten-free bread?", a: "Not yet: our bakery handles wheat all day, so we cannot promise it." },
];
export function Faq() {
  return (
    <section className="py-20">
      <h2 className="text-3xl font-semibold">Questions</h2>
      <div className="mt-8 divide-y">
        {faqs.map((f) => (
          <details key={f.q} className="py-4">
            <summary className="font-medium">{f.q}</summary>
            <p className="mt-2 text-muted-foreground">{f.a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
` },
  cta: { at: '<section', code: LINK + `
export function Cta() {
  return (
    <section className="rounded-2xl bg-primary px-6 py-16 text-center text-primary-foreground">
      <h2 className="text-3xl font-semibold">Your first loaf is on us</h2>
      <p className="mt-3">Try a week of Maison Levain bread with no commitment.</p>
      <Link href="/order?promo=first" className="mt-8 inline-block rounded-md bg-background px-5 py-3 text-foreground">Claim my free loaf</Link>
    </section>
  );
}
` },
  footer: { at: '<footer', code: LINK + `
export function Footer() {
  return (
    <footer className="border-t py-12">
      <div className="mx-auto flex max-w-5xl flex-col gap-6 px-6 md:flex-row md:justify-between">
        <div>
          <p className="font-semibold">Maison Levain</p>
          <p className="mt-2 text-sm text-muted-foreground">12 rue des Capucins, 69001 Lyon</p>
        </div>
        <nav className="flex gap-6 text-sm">
          <Link href="/menu">Menu</Link>
          <Link href="/pricing">Subscriptions</Link>
          <Link href="/legal">Legal notice</Link>
        </nav>
      </div>
      <p className="mt-8 text-center text-xs text-muted-foreground">© 2026 Maison Levain</p>
    </footer>
  );
}
` },
  navbar: { at: '<header', code: LINK + BTN + `
export function Navbar() {
  return (
    <header className="border-b">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <Link href="/" className="font-semibold">Maison Levain</Link>
        <nav className="flex gap-6 text-sm">
          <Link href="/menu">Menu</Link>
          <Link href="/pricing">Subscriptions</Link>
          <Link href="/about">About</Link>
        </nav>
        <Button asChild size="sm"><Link href="/order">Order</Link></Button>
      </div>
    </header>
  );
}
` },
  stats: { at: '<section', code: `export function Stats() {
  return (
    <section className="py-16">
      <div className="mx-auto grid max-w-5xl grid-cols-2 gap-8 md:grid-cols-4">
        <div><p className="text-4xl font-bold">1,200</p><p className="text-sm">loaves every week</p></div>
        <div><p className="text-4xl font-bold">12 years</p><p className="text-sm">of the same starter</p></div>
        <div><p className="text-4xl font-bold">6am</p><p className="text-sm">first delivery</p></div>
        <div><p className="text-4xl font-bold">4.9/5</p><p className="text-sm">from 380 reviews</p></div>
      </div>
    </section>
  );
}
` },
  team: { at: '<section', code: `const team = [
  { name: "Claire Martin", role: "Head baker", img: "/deckhand-placeholder.svg" },
  { name: "Yanis Benali", role: "Pastry", img: "/deckhand-placeholder.svg" },
  { name: "Léa Roux", role: "Deliveries", img: "/deckhand-placeholder.svg" },
];
export function Team() {
  return (
    <section className="py-20">
      <h2 className="text-3xl font-semibold">The bakers</h2>
      <div className="mt-10 grid grid-cols-3 gap-8">
        {team.map((m) => (
          <div key={m.name} className="text-center">
            <img src={m.img} alt={m.name} className="mx-auto size-20 rounded-full" />
            <p className="mt-3 font-semibold">{m.name}</p>
            <p className="text-sm text-muted-foreground">{m.role}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
` },
  'logo-cloud': { at: '<section', code: `export function Logos() {
  return (
    <section className="py-12 text-center">
      <p className="text-sm text-muted-foreground">Served in Lyon's best cafés</p>
      <div className="mt-6 flex flex-wrap items-center justify-center gap-10">
        <img src="/deckhand-placeholder.svg" alt="Café Pistache" className="h-6" />
        <img src="/deckhand-placeholder.svg" alt="Le Comptoir" className="h-6" />
        <img src="/deckhand-placeholder.svg" alt="Maison Rive" className="h-6" />
        <img src="/deckhand-placeholder.svg" alt="Bistro Nord" className="h-6" />
      </div>
    </section>
  );
}
` },
  contact: { at: '<section', code: `export function Contact() {
  return (
    <section className="grid gap-12 py-20 md:grid-cols-2">
      <div>
        <h2 className="text-3xl font-semibold">Order for your café</h2>
        <p className="mt-3 text-muted-foreground">Tell us what you need and we reply within one working day.</p>
      </div>
      <form action="/api/contact" method="post" className="space-y-4">
        <label className="block text-sm">Name<input name="name" placeholder="Your name" className="mt-1 w-full rounded-md border px-3 py-2" /></label>
        <label className="block text-sm">Email<input type="email" name="email" placeholder="you@example.com" className="mt-1 w-full rounded-md border px-3 py-2" /></label>
        <label className="block text-sm">Message<textarea name="message" placeholder="How many loaves, which days" className="mt-1 w-full rounded-md border px-3 py-2" /></label>
        <button type="submit" className="rounded-md bg-primary px-4 py-2 text-primary-foreground">Send</button>
      </form>
    </section>
  );
}
` },
  login: { at: '<section', code: LINK + `
export function Login() {
  return (
    <section className="mx-auto max-w-sm py-20">
      <h1 className="text-2xl font-semibold">Sign in to your account</h1>
      <p className="mt-2 text-sm text-muted-foreground">Manage your deliveries and subscriptions.</p>
      <form action="/api/login" method="post" className="mt-8 space-y-4">
        <label className="block text-sm">Email<input type="email" name="email" placeholder="you@example.com" className="mt-1 w-full rounded-md border px-3 py-2" /></label>
        <label className="block text-sm">Password<input type="password" name="password" className="mt-1 w-full rounded-md border px-3 py-2" /></label>
        <button type="submit" className="w-full rounded-md bg-primary px-4 py-2 text-primary-foreground">Sign in</button>
      </form>
      <p className="mt-6 text-sm">New here? <Link href="/signup" className="underline">Create an account</Link></p>
    </section>
  );
}
` },
  comparison: { at: '<section', code: `export function Comparison() {
  return (
    <section className="py-20">
      <h2 className="text-3xl font-semibold">Maison Levain vs. supermarket bread</h2>
      <table className="mt-8 w-full">
        <thead><tr><th className="py-2"></th><th>Maison Levain</th><th>Supermarket</th></tr></thead>
        <tbody>
          <tr className="border-t"><td className="py-2">Fermentation</td><td>36 hours</td><td>2 hours</td></tr>
          <tr className="border-t"><td className="py-2">Additives</td><td>None</td><td>Several</td></tr>
          <tr className="border-t"><td className="py-2">Delivered warm</td><td>Yes</td><td>No</td></tr>
        </tbody>
      </table>
    </section>
  );
}
` },
  blog: { at: '<section', code: LINK + `const posts = [
  { title: "Why we ferment for 36 hours", excerpt: "Slow dough, better crust and easier digestion.", date: "12 Sep 2026", href: "/blog/fermentation", img: "/deckhand-placeholder.svg" },
  { title: "Keeping sourdough fresh all week", excerpt: "Linen, not plastic: three habits that work.", date: "28 Aug 2026", href: "/blog/fresh", img: "/deckhand-placeholder.svg" },
  { title: "Meet our flour farmers", excerpt: "Two families, one valley, and the wheat in your loaf.", date: "3 Aug 2026", href: "/blog/farmers", img: "/deckhand-placeholder.svg" },
];
export function Blog() {
  return (
    <section className="py-20">
      <h2 className="text-3xl font-semibold">From the bakery</h2>
      <div className="mt-10 grid gap-8 md:grid-cols-3">
        {posts.map((p) => (
          <article key={p.href}>
            <img src={p.img} alt={p.title} className="rounded-lg" />
            <p className="mt-3 text-xs text-muted-foreground">{p.date}</p>
            <h3 className="mt-1 font-semibold">{p.title}</h3>
            <p className="mt-2 text-sm text-muted-foreground">{p.excerpt}</p>
            <Link href={p.href} className="mt-3 inline-block text-sm underline">Read more</Link>
          </article>
        ))}
      </div>
    </section>
  );
}
` },
  button: { at: '<Button', code: LINK + BTN + `
export function Order() {
  return (
    <div className="flex justify-center">
      <Button asChild size="lg"><Link href="/order">Order your first loaf</Link></Button>
    </div>
  );
}
` },
  badge: { at: '<span', code: `export function Tag() {
  return (
    <p className="text-center"><span className="rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary">New: rye loaves on Fridays</span></p>
  );
}
` },
  card: { at: '<div className="rounded-xl', code: `export function Loaf() {
  return (
    <div className="grid gap-6 md:grid-cols-3">
      <div className="rounded-xl border p-6">
        <h3 className="font-semibold">Country sourdough</h3>
        <p className="mt-2 text-sm text-muted-foreground">Our everyday loaf: a dark crust, an open crumb and a gentle sourness.</p>
      </div>
    </div>
  );
}
` },
  input: { at: '<input', code: `export function Newsletter() {
  return (
    <form action="/api/newsletter" method="post" className="flex gap-2">
      <input type="email" name="email" placeholder="you@example.com" className="rounded-md border px-3 py-2" />
      <button type="submit" className="rounded-md bg-primary px-4 py-2 text-primary-foreground">Get the weekly menu</button>
    </form>
  );
}
` },
  'text-effect': { at: '<h1', code: `export function Headline() {
  return (
    <div className="py-16 text-center">
      <h1 className="text-5xl font-bold">Sourdough delivered warm</h1>
    </div>
  );
}
` },
};

/** Slots checked against another kind's owner section (the section an owner would click to be offered them). */
export const REF_OF = { signup: 'login', 'forgot-password': 'login', integrations: 'features', marquee: 'logo-cloud' };

export function referenceFor(slot) {
  return REFERENCE[slot] ? slot : (REF_OF[slot] || null);
}

/* ------------------------------------------------------------------ the throwaway site */

// the radix-ui umbrella's parts: a design's @radix-ui/react-<x> is rewritten to radix-ui/<x> (materialize.radixUmbrella)
const RADIX_PARTS = ['accessible-icon', 'accordion', 'alert-dialog', 'aspect-ratio', 'avatar', 'checkbox', 'collapsible',
  'context-menu', 'dialog', 'direction', 'dropdown-menu', 'form', 'hover-card', 'label', 'menubar', 'navigation-menu',
  'one-time-password-field', 'password-toggle-field', 'popover', 'portal', 'progress', 'radio-group', 'scroll-area',
  'select', 'separator', 'slider', 'slot', 'switch', 'tabs', 'toast', 'toggle', 'toggle-group', 'toolbar', 'tooltip',
  'visually-hidden'];

/** What `dh scaffold` gives an owner (templates/scaffold): Next + Tailwind 4 + tokens + cn + Button, deps "installed". */
export function makeSite(dir, { base = 'radix' } = {}) {
  const scaffold = path.join(SKILL_DIR, 'templates', 'scaffold');
  const primitives = base === 'base-ui' ? { '@base-ui/react': '^1.0.0' } : { 'radix-ui': '^1.4.3' };
  const deps = { next: '16.0.0', react: '19.2.0', 'react-dom': '19.2.0', clsx: '^2.1.1', 'tailwind-merge': '^3.3.1',
    'class-variance-authority': '^0.7.1', 'lucide-react': '^0.500.0', 'tw-animate-css': '^1.3.0', ...primitives };
  const dev = { tailwindcss: '^4', '@tailwindcss/postcss': '^4', typescript: '^5' };
  const w = (rel, text) => { fs.mkdirSync(path.dirname(path.join(dir, rel)), { recursive: true }); fs.writeFileSync(path.join(dir, rel), text); };
  w('package.json', JSON.stringify({ name: 'maison-levain', private: true, dependencies: deps, devDependencies: dev }, null, 2));
  w('tsconfig.json', JSON.stringify({ compilerOptions: { jsx: 'preserve', paths: { '@/*': ['./*'] } } }, null, 2));
  for (const rel of ['app/globals.css', 'lib/utils.ts', 'components/ui/button.tsx']) w(rel, fs.readFileSync(path.join(scaffold, rel), 'utf8'));
  if (base === 'base-ui') w('components/ui/button.tsx', fs.readFileSync(path.join(scaffold, 'components/ui/button.tsx'), 'utf8').replace('import { Slot } from "radix-ui"\n', ''));
  w('app/page.tsx', 'export default function Page() { return null; }\n');
  for (const d of Object.keys({ ...deps, ...dev })) w(`node_modules/${d}/package.json`, JSON.stringify({ name: d, version: '0.0.0' }));
  if (base !== 'base-ui') for (const p of RADIX_PARTS) w(`node_modules/radix-ui/dist/${p}.mjs`, 'export {};\n');
  w('.deckhand/brief.json', JSON.stringify({ name: 'Maison Levain', brand: { name: 'Maison Levain' } }));
  w('.deckhand/sitemap.json', JSON.stringify({ nav: { header: ['route:/menu', 'route:/pricing', 'route:/about'], footer: ['route:/legal', 'mailto:hello@maison-levain.fr'] },
    pages: [{ route: '/', title: 'Home' }, { route: '/menu', title: 'Menu' }, { route: '/pricing', title: 'Subscriptions' }, { route: '/about', title: 'About' }, { route: '/legal', title: 'Legal notice' }] }));
  for (const [slot, ref] of Object.entries(REFERENCE)) w(`components/ref/${slot}.tsx`, ref.code);
  return detectProject(dir);
}

/** The staging context for one kind of section in a site (the owner's element, located like a click would). */
export function contextFor(prof, slot) {
  const ref = REFERENCE[slot];
  const rel = `components/ref/${slot}.tsx`;
  const code = fs.readFileSync(path.join(prof.root, rel), 'utf8');
  const ast = parse(rel, code);
  const i = code.indexOf(ref.at);
  const before = code.slice(0, i);
  const el = findElementAt(ast, code, before.split('\n').length, i - before.lastIndexOf('\n'));
  if (!el) throw new Error(`fitcheck: no element at "${ref.at}" in the ${slot} reference`);
  return stagingContext(prof, { code, ast, el, slot, sessionId: 'fitcheck', checkImports: false, log: () => {} });
}

/* ------------------------------------------------------------------ one design, many designs */

/** Stage one catalog item against the owner section of its kind; the staged files are removed afterwards. */
export async function checkItem(site, item, { explain = false } = {}) {
  const slot = referenceFor(item.slot);
  const out = { id: item.id, slot: item.slot };
  if (!slot) return { ...out, verdict: 'unchecked', why: `no owner section of kind "${item.slot}"` };
  const prof = site.prof(item.base === 'base-ui' ? 'base-ui' : 'radix');
  const ctx = site.ctx(prof, slot);
  let r;
  try { r = await stageCandidate(ctx, item); } catch (e) {
    return { ...out, verdict: 'broken', why: 'ENGINE_ERROR: ' + String(e && e.message || e).slice(0, 200) };
  }
  if (r.skip) {
    const why = r.skip.why + (r.skip.detail ? ': ' + r.skip.detail : '');
    if (r.skip.why === 'POOR_FIT') return { ...out, verdict: 'refused', why };
    if (BROKEN.has(r.skip.why)) return { ...out, verdict: 'broken', why };
    return { ...out, verdict: 'unreachable', why };
  }
  const v = r.v || r.held;
  fs.rmSync(path.join(prof.root, v.dir), { recursive: true, force: true });
  const f = v.fit;
  const res = { ...out, verdict: f.carried >= f.of ? 'fits' : 'partial', carried: f.carried, of: f.of };
  if (v.missingDeps.length) res.needs = [...v.missingDeps].sort();
  if (f.demoVisual) res.demo = f.demoVisual;
  if (f.dropped.length) res.dropped = f.dropped.map((d) => (typeof d === 'string' ? d : d.text || d.role || JSON.stringify(d))).slice(0, 8);
  if (explain && f.demo.length) res.demoWords = f.demo.slice(0, 6);
  return res;
}

/** A throwaway site per primitive base, and one staging context per kind of section (built on first use). */
export function openSite() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dh-fitcheck-'));
  const profs = {};
  const ctxs = new Map();
  return {
    dir,
    prof(base) { return profs[base] || (profs[base] = makeSite(path.join(dir, base), { base })); },
    ctx(prof, slot) {
      const k = prof.root + '|' + slot;
      if (!ctxs.has(k)) ctxs.set(k, contextFor(prof, slot));
      return ctxs.get(k);
    },
    close() { fs.rmSync(dir, { recursive: true, force: true }); },
  };
}

/** A deterministic sample: items sorted by id, taken round-robin across kinds so every kind is represented. */
export function sampleOf(items, n) {
  if (!n || n >= items.length) return [...items].sort((a, b) => a.id.localeCompare(b.id));
  const by = new Map();
  for (const it of [...items].sort((a, b) => a.id.localeCompare(b.id))) {
    const k = referenceFor(it.slot) ? it.slot : '~';
    if (!by.has(k)) by.set(k, []);
    by.get(k).push(it);
  }
  const keys = [...by.keys()].sort();
  const out = [];
  for (let i = 0; out.length < n; i++) {
    let any = false;
    for (const k of keys) if (by.get(k)[i] && out.length < n) { out.push(by.get(k)[i]); any = true; }
    if (!any) break;
  }
  return out;
}

/**
 * Check a registry's designs (or any list). The same items give the same verdicts, in id order.
 * {id, items, sample, concurrency, onProgress, explain} -> {registry, checked, counts, results}
 */
export async function fitCheck({ id = null, items, sample = 0, concurrency = 4, onProgress = () => {}, explain = false }) {
  const list = sampleOf(items, sample);
  const site = openSite();
  const results = new Array(list.length);
  let next = 0;
  let done = 0;
  // staging is per-item (its own folder); the fetch is what takes time, so a few run at once
  const worker = async () => {
    for (;;) {
      const i = next++;
      if (i >= list.length) return;
      results[i] = await checkItem(site, list[i], { explain });
      onProgress({ done: ++done, of: list.length, id: list[i].id, verdict: results[i].verdict });
    }
  };
  try {
    await Promise.all(Array.from({ length: Math.max(1, Math.min(concurrency, list.length)) }, worker));
  } finally { site.close(); }
  results.sort((a, b) => a.id.localeCompare(b.id));
  const counts = Object.fromEntries(VERDICTS.map((v) => [v, results.filter((r) => r.verdict === v).length]));
  return { registry: id, checked: results.length, of: items.length, counts, results };
}

/* ------------------------------------------------------------------ verdicts on disk */

/** Write verdicts ({id: {v, why?, needs?}}) for one registry, merged over the ones already there. */
export function recordVerdicts(res, { dir = localChecksDir(), version = skillVersion() } = {}) {
  if (!res.registry || !/^[a-z0-9][a-z0-9-]*$/.test(res.registry)) throw Object.assign(new Error('a registry id is needed to record verdicts'), { code: 'BAD_ID' });
  const file = path.join(dir, res.registry + '.json');
  let have = {};
  try { have = JSON.parse(fs.readFileSync(file, 'utf8')).verdicts || {}; } catch { /* first run */ }
  for (const r of res.results) {
    if (r.verdict === 'unreachable') continue;                       // a network failure is not a verdict
    have[r.id] = { v: r.verdict, ...(r.why && r.verdict !== 'fits' ? { why: r.why } : {}), ...(r.needs ? { needs: r.needs } : {}),
      ...(r.of ? { carried: r.carried, of: r.of } : {}) };
  }
  const sorted = Object.fromEntries(Object.keys(have).sort().map((k) => [k, have[k]]));
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(file, JSON.stringify({ version: 1, registry: res.registry, deckhand: version, verdicts: sorted }, null, 1) + '\n');
  return { file, verdicts: Object.keys(sorted).length };
}

export function skillVersion() {
  try { return /^version:\s*"?([\d.]+)/m.exec(fs.readFileSync(path.join(SKILL_DIR, 'SKILL.md'), 'utf8'))[1]; } catch { return null; }
}

/* ------------------------------------------------------------------ the report */

const esc = (s) => String(s).replace(/\|/g, '\\|').replace(/\n/g, ' ');

/** A Markdown report: counts, then per kind, then every broken and refused design with its reason. */
export function fitMarkdown(res) {
  const L = [`# Fit check${res.registry ? ' — ' + res.registry : ''}`, '',
    `${res.checked} of ${res.of} designs staged against an owner section of their kind (a Deckhand scaffold site).`, '',
    '| verdict | designs |', '|---|---|', ...VERDICTS.filter((v) => res.counts[v]).map((v) => `| ${v} | ${res.counts[v]} |`), ''];
  const kinds = [...new Set(res.results.map((r) => r.slot))].sort();
  L.push('## By kind', '', '| kind | fits | partial | refused | broken | unreachable | unchecked |', '|---|---|---|---|---|---|---|');
  for (const k of kinds) {
    const rs = res.results.filter((r) => r.slot === k);
    L.push(`| ${k} | ` + VERDICTS.map((v) => rs.filter((r) => r.verdict === v).length || '').join(' | ') + ' |');
  }
  for (const v of ['broken', 'refused', 'partial', 'unreachable']) {
    const rs = res.results.filter((r) => r.verdict === v);
    if (!rs.length) continue;
    L.push('', `## ${v[0].toUpperCase() + v.slice(1)} (${rs.length})`, '');
    for (const r of rs) L.push(`- \`${r.id}\` (${r.slot})` + (r.why ? ': ' + esc(r.why) : '') + (r.dropped ? ' — dropped: ' + r.dropped.map(esc).join(', ') : '')
      + (r.of ? ` — carries ${r.carried}/${r.of}` : ''));
  }
  const needs = {};
  for (const r of res.results) for (const n of r.needs || []) needs[n] = (needs[n] || 0) + 1;
  if (Object.keys(needs).length) {
    L.push('', '## Packages a project would install first', '');
    for (const [n, c] of Object.entries(needs).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))) L.push(`- ${n} (${c})`);
  }
  return L.join('\n') + '\n';
}
