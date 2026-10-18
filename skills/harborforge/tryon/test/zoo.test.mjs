// The component zoo: one real site with a section of every common kind (a notice bar, stats, a logo row, a team,
// a comparison table, a contact form, a newsletter, a login, product and blog cards, a lone card, a button), every
// design variant screenshotted in Chromium and checked for words that are not the owner's, words of theirs that
// went missing, and broken layout. Each thing it found, pinned here offline.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { offline } from './helpers.mjs';
import { extractUnits, parameterize, bind, contentProp, contentCount, ownerLogos } from '../lib/transplant.mjs';
import { markDemo, unmarkDemo, rendersChildren, noVariantsWhy, fitGate } from '../lib/engine.mjs';
import { compatFixes, fitProjectPrimitives } from '../lib/materialize.mjs';
import { detectProject } from '../lib/project.mjs';
import { tempSite } from './helpers.mjs';
import fs from 'node:fs';
import path from 'node:path';
import { slotFromName } from '../lib/slots.mjs';

const require = createRequire(import.meta.url);
const { parse, findElementAt } = require('../lib/ast.cjs');

offline();

function unitsAt(code, needle) {
  const ast = parse('o.tsx', code);
  const i = code.indexOf(needle);
  const b = code.slice(0, i);
  return extractUnits(code, findElementAt(ast, code, b.split('\n').length, i - b.lastIndexOf('\n')), ast);
}
function swap(orig, cand, opts = {}) {
  const p = parameterize('c.tsx', cand, { kind: 'default' }, { stripChrome: true, ...opts });
  const b = bind(orig, p, {});
  return { p, b, usage: `<X${contentProp(p.prop, b.props)} />` };
}

/* ------------------------------------------------------------------ a notice bar */

const BANNER = `export function Banner() {
  return (
    <div className="bg-emerald-600 px-6 py-2 text-center text-sm text-white">
      New: weekend deep-cleans for offices in Lyon. <Link href="/weekend" className="font-semibold underline">Book a slot</Link>
    </div>
  );
}`;
const CTA = `export default function CallToAction() {
  return (
    <section className="py-16">
      <h2 className="text-4xl font-semibold">Ready to Get Started?</h2>
      <p className="mt-4">Join thousands of teams already using our platform.</p>
      <Button asChild><Link href="#">Start Free Trial</Link></Button>
      <Button asChild variant="outline"><Link href="#">Talk to Sales</Link></Button>
    </section>
  )
}`;

test('notice bar: the words beside a link are the owner\'s too, and their one line becomes the headline', () => {
  const orig = unitsAt(BANNER, '<div');
  assert.deepEqual(orig.units.map((u) => [u.role, u.text]), [['text', 'New: weekend deep-cleans for offices in Lyon.'], ['action', 'Book a slot']]);
  const { b, usage } = swap(orig, CTA);
  assert.match(usage, /heading1: <>New: weekend deep-cleans for offices in Lyon\.<\/>/);
  assert.match(usage, /action1: <>Book a slot<\/>, action1Href: "\/weekend"/);
  assert.match(usage, /action2Show: false/);
  assert.equal(b.carried.length, 2);
  assert.ok(!b.demo.some((d) => d.text === 'Ready to Get Started?'), 'the design headline is not left as demo copy');
});

test('words on both sides of a link are one sentence, carried whole with the link inside', () => {
  const code = `export function C() { return (<section><p>Call us at <a href="tel:+331">01 23 45 67 89</a> or write any time.</p></section>); }`;
  const orig = unitsAt(code, '<section');
  assert.equal(orig.units.length, 1);
  assert.equal(orig.units[0].role, 'text');
  assert.match(orig.units[0].src, /^Call us at <a href="tel:\+331">01 23 45 67 89<\/a> or write any time\.$/);
});

/* ------------------------------------------------------------------ stats */

const STATS = `export function Stats() {
  return (
    <section className="bg-muted/50 py-16">
      <div className="mx-auto grid max-w-5xl grid-cols-2 gap-8 md:grid-cols-4">
        <div><p className="text-4xl font-bold">120+</p><p className="text-sm">offices cleaned nightly</p></div>
        <div><p className="text-4xl font-bold">98%</p><p className="text-sm">contracts renewed</p></div>
        <div><p className="text-4xl font-bold">24h</p><p className="text-sm">to get a quote</p></div>
        <div><p className="text-4xl font-bold">7/7</p><p className="text-sm">days of service</p></div>
      </div>
    </section>
  );
}`;
const STATS_DESIGN = `export default function StatsSection() {
  return (
    <section>
      <div>
        <h2 className="text-4xl font-semibold">Tailark in numbers</h2>
        <p className="text-muted-foreground mt-4">Our platform continues to grow with developers and businesses.</p>
      </div>
      <div className="mt-8 grid grid-cols-2 gap-4 md:grid-cols-4">
        <div><div className="text-4xl font-bold">90+</div><p className="text-muted-foreground">Integrations</p></div>
        <div><div className="text-4xl font-bold">56%</div><p className="text-muted-foreground">Productivity Boost</p></div>
        <div><div className="text-4xl font-bold">24/7</div><p className="text-muted-foreground">Customer Support</p></div>
        <div><div className="text-4xl font-bold">10k+</div><p className="text-muted-foreground">Active Users</p></div>
      </div>
    </section>
  )
}`;

test('stats: a figure (120+, 98%, 24h, 7/7) pairs with the design\'s figure, its label with its label — never the headline', () => {
  const orig = unitsAt(STATS, '<section');
  assert.deepEqual(orig.units.filter((u) => u.role === 'figure').map((u) => u.text), ['120+', '98%', '24h', '7/7']);
  const { p, b, usage } = swap(orig, STATS_DESIGN);
  assert.deepEqual(p.slots.filter((s) => s.role === 'figure').map((s) => s.demo), ['90+', '56%', '24/7', '10k+'], 'short figures are slots too');
  assert.equal(b.carried.length, 8);
  for (const [fig, label] of [['120+', 'offices cleaned nightly'], ['7/7', 'days of service']]) {
    assert.match(usage, new RegExp(`figure\\d: <>${fig.replace('+', '\\+')}</>, text\\d: <>${label}</>`));
  }
  assert.ok(b.demo.some((d) => d.text === 'Tailark in numbers'), 'the headline stays the design\'s, dashed');
  assert.ok(!/heading1: <>120\+/.test(usage));
});

test('stats: `<p><span>99.9%</span> Uptime guarantee.</p>` leads with a figure, not a title', () => {
  const design = `export default function S() { return (<section><h2>Trusted</h2><div className="grid grid-cols-3">
    <div><p><span className="text-foreground">99.9%</span> Uptime guarantee.</p></div>
    <div><p><span className="text-foreground">10M+</span> API requests daily.</p></div>
    <div><p><span className="text-foreground">500+</span> Enterprise customers.</p></div></div></section>) }`;
  const p = parameterize('c.tsx', design, { kind: 'default' }, {});
  assert.deepEqual(p.slots.filter((s) => s.role === 'figure').map((s) => s.demo), ['99.9%', '10M+', '500+']);
});

/* ------------------------------------------------------------------ logo cloud */

const LOGOS = `export function Logos() {
  return (
    <section className="py-12 text-center">
      <p className="text-sm text-muted-foreground">Trusted by teams in Lyon</p>
      <div className="mt-6 flex flex-wrap items-center justify-center gap-10">
        <img src="/next.svg" alt="Brightline" className="h-6" />
        <img src="/vercel.svg" alt="Atelier Nord" className="h-6" />
        <img src="/globe.svg" alt="Maison Rive" className="h-6" />
      </div>
    </section>
  );
}`;
const LOGO_DESIGN = `import { Spotify } from './spotify'
import { Vercel } from './vercel'
import { Hulu } from './hulu'
export default function LogoCloud() {
  return (
    <section>
      <p className="text-muted-foreground font-medium">Trusted by teams at :</p>
      <div className="mt-4 flex items-center gap-12">
        <Spotify height={22} width={73} />
        <Vercel height={20} width={76} />
        <Hulu height={16} width={50} />
      </div>
    </section>
  )
}`;

test('logo cloud: the owner\'s own logos take the design\'s row (same spacing); its demo brands never show as theirs', () => {
  const orig = unitsAt(LOGOS, '<section');
  assert.equal(ownerLogos(orig).length, 3);
  const logoLocals = ['Spotify', 'Vercel', 'Hulu'];
  const { p, b, usage } = swap(orig, LOGO_DESIGN, { logoLocals, logoSwap: true });
  assert.deepEqual(p.logoSwaps, ['logoRow1']);
  assert.match(p.code, /content\.logoRow1 \?\? \(<><Spotify/);
  assert.match(p.code, /className="mt-4 flex items-center gap-12 flex-wrap"/, 'more logos than the design had: the row wraps on a phone');
  assert.match(usage, /logoRow1: <><img src="\/next\.svg" alt="Brightline" className="h-6" \/>/);
  assert.match(usage, /text1: <>Trusted by teams in Lyon<\/>/);
  assert.equal(b.carried.length, contentCount(orig), 'the line and all three logos');
  assert.deepEqual(b.carried.filter((c) => c.role === 'image').map((c) => c.text), ['Brightline', 'Atelier Nord', 'Maison Rive']);
  // an owner without logos: the design's demo brands are hidden, not shown
  const bare = swap(unitsAt('export function L() { return (<section><p>Our partners</p></section>); }', '<section'), LOGO_DESIGN, { logoLocals, logoSwap: false });
  assert.deepEqual(bare.p.logoRows, ['logos1']);
  assert.match(bare.p.code, /content\.logos1Show === true && \(/);
});

test('a logo row\'s label goes with it only when the other siblings are short labels — never a whole card', () => {
  const design = `import { Slack } from './slack'
export default function F() { return (<section><div className="grid grid-cols-3">
  <div className="card"><h3>Integrations that just work</h3><p>Connect the tools your team already relies on every day, without code.</p><div className="flex"><Slack /><Slack /></div></div>
  <div className="card"><h3>Fast</h3><p>Everything loads instantly for every member of the team, anywhere.</p></div>
</div></section>) }`;
  const p = parameterize('c.tsx', design, { kind: 'default' }, { logoLocals: ['Slack'] });
  assert.match(p.code, /logos1Show === true && \(<div className="flex">/, 'only the logo row hides');
  assert.ok(p.slots.some((s) => s.demo === 'Integrations that just work'), 'the card keeps its words');
});

/* ------------------------------------------------------------------ team */

const TEAM = `const team = [
  { name: "Nadia B.", role: "Founder", img: "/globe.svg" },
  { name: "Karim L.", role: "Operations", img: "/window.svg" },
  { name: "Julie P.", role: "Client care", img: "/file.svg" },
];
export function Team() {
  return (
    <section className="py-20">
      <h2 className="text-3xl font-semibold">Meet the team</h2>
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
}`;

test('team: a name shown in a <span> AND used as the photo\'s alt is still a field; the owner\'s photo gets the owner\'s name', () => {
  const design = `const members = [
  { name: 'Meschac Irung', role: 'Frontend Engineer', src: 'https://avatars.githubusercontent.com/u/1' },
  { name: 'Bernard Ngandu', role: 'Backend Engineer', src: 'https://avatars.githubusercontent.com/u/2' },
]
export default function TeamSection() {
  return (
    <section>
      <h2 className="text-3xl font-bold">Meet Our Team</h2>
      <div className="grid gap-6">
        {members.map((member, index) => (
          <div key={index} className="grid grid-cols-[auto_1fr] gap-3">
            <Image src={member.src} alt={member.name} width={44} height={44} />
            <div><span className="font-medium">{member.name}</span><div className="text-sm">{member.role}</div></div>
          </div>
        ))}
      </div>
    </section>
  )
}`;
  const { b, usage } = swap(unitsAt(TEAM, '<section'), design);
  assert.match(usage, /\{ "name": "Nadia B\.", "role": "Founder", "src": "\/globe\.svg" \}/);
  assert.ok(!/Meschac/.test(usage));
  assert.equal(b.dropped.length, 0);
});

test('team: name then role stay name then role — the "longest text is the bio" rule needs words that uneven', () => {
  const design = `const people = [
  { name: 'Meschac Irung', role: 'Frontend Engineer at Acme', bio: 'Passionate about intuitive UIs and web performance. Specializes in React and TypeScript with 5+ years.', avatar: 'https://avatars.githubusercontent.com/u/1' },
]
export default function T() {
  return (<section><h2>Meet Our Founders</h2>{people.map((p) => (
    <div key={p.name}><img src={p.avatar} alt={p.name} /><h3>{p.name}</h3><p>{p.role}</p><p>{p.bio}</p></div>
  ))}</section>)
}`;
  const { usage } = swap(unitsAt(TEAM, '<section'), design);
  assert.match(usage, /"name": "Nadia B\.", "role": "Founder", "bio": <span data-dh-demo="">/);
});

/* ------------------------------------------------------------------ comparison table */

const TABLE = `export function Comparison() {
  return (
    <section className="py-20">
      <h2 className="text-3xl font-semibold">Us vs. a typical agency</h2>
      <table className="mt-8 w-full">
        <thead><tr><th className="py-2"></th><th>Sparkle Clean</th><th>Typical agency</th></tr></thead>
        <tbody>
          <tr className="border-t"><td className="py-2">Same crew every night</td><td>Yes</td><td>Rarely</td></tr>
          <tr className="border-t"><td className="py-2">Photo reports</td><td>Every visit</td><td>No</td></tr>
          <tr className="border-t"><td className="py-2">Contract</td><td>Monthly</td><td>12 months</td></tr>
        </tbody>
      </table>
    </section>
  );
}`;
const COMPARATOR = `const features = [
  { name: 'Integrations', free: '5', pro: 'Unlimited' },
  { name: 'API Calls', free: '10K/mo', pro: '500K/mo' },
  { name: 'Analytics Dashboard', free: false, pro: true },
]
export default function Comparator() {
  return (
    <section>
      <h2 className="font-serif text-4xl">Free vs Pro</h2>
      <p className="text-muted-foreground">See what you get with each plan.</p>
      <div className="grid grid-cols-3">
        <div className="p-4"></div>
        <div className="p-4"><p className="font-medium">Free</p><p className="text-2xl">$0</p></div>
        <div className="p-4"><p className="font-medium">Pro</p><p className="text-2xl">$29</p></div>
      </div>
      {features.map((feature) => (
        <div key={feature.name} className="grid grid-cols-3 border-t">
          <div className="p-4 text-sm">{feature.name}</div>
          <div className="p-4">{typeof feature.free === 'boolean' ? <Check /> : <span className="text-foreground">{feature.free}</span>}</div>
          <div className="p-4">{typeof feature.pro === 'boolean' ? <Check /> : <span className="font-medium">{feature.pro}</span>}</div>
        </div>
      ))}
    </section>
  )
}`;

test('comparison: the owner\'s table goes into a design\'s table row by row, cell by cell, column names over the columns', () => {
  const orig = unitsAt(TABLE, '<section');
  const { b, usage } = swap(orig, COMPARATOR);
  assert.match(usage, /\{ "name": "Same crew every night", "free": "Yes", "pro": "Rarely" \}/);
  assert.match(usage, /\{ "name": "Contract", "free": "Monthly", "pro": "12 months" \}/);
  assert.match(usage, /<>Sparkle Clean<\/>/);
  assert.match(usage, /<>Typical agency<\/>/);
  assert.match(usage, /heading1: <>Us vs\. a typical agency<\/>/);
  assert.equal(b.carried.length, contentCount(orig));
  assert.equal(b.dropped.length, 0);
});

test('comparison: a design with no table (plan cards, a plans list) gets none of the rows — too little to offer', () => {
  const orig = unitsAt(TABLE, '<section');
  const cards = `export default function Pricing() { return (<section><h2>Pricing</h2><div className="grid grid-cols-3">
    <div><h3>Free</h3><p>For hobby projects</p><span>$0</span><Button>Get Started</Button></div>
    <div><h3>Pro</h3><p>For small teams</p><span>$59</span><Button>Get Started</Button></div>
    <div><h3>Startup</h3><p>For growing teams</p><span>$99</span><Button>Get Started</Button></div></div></section>) }`;
  const { b } = swap(orig, cards);
  assert.ok(b.carried.length < Math.ceil(contentCount(orig) / 2), `carried ${b.carried.length}`);
  assert.ok(b.dropped.some((d) => d.text === 'Same crew every night'));
});

/* ------------------------------------------------------------------ forms */

const CONTACT = `export function Contact() {
  return (
    <section className="grid gap-12 md:grid-cols-2">
      <div>
        <h2 className="text-3xl font-semibold">Talk to us</h2>
        <p className="mt-3 text-muted-foreground">We reply within one working day.</p>
      </div>
      <form action="/api/contact" method="post" className="space-y-4">
        <div><Label htmlFor="name">Name</Label><Input id="name" name="name" placeholder="Your name" /></div>
        <div><Label htmlFor="msg">Message</Label><Textarea id="msg" name="message" placeholder="Your office, size and schedule" /></div>
        <Button type="submit">Send message</Button>
      </form>
    </section>
  );
}`;

test('forms: the owner\'s own form (action, fields, button) takes the design form\'s place — no invented "Company size"', () => {
  const orig = unitsAt(CONTACT, '<section');
  assert.equal(orig.forms.length, 1);
  const design = `export default function ContactSection() {
  return (
    <section>
      <h2 className="text-4xl">Contact Sales</h2>
      <p>We'd love to hear from you.</p>
      <form className="space-y-4 rounded-xl border p-6">
        <label>Company size</label>
        <Input placeholder="Acme Inc." />
        <Button>Submit</Button>
      </form>
    </section>
  )
}`;
  const p = parameterize('c.tsx', design, { kind: 'default' }, { forms: 'swap' });
  assert.deepEqual(p.formSwaps, ['form1']);
  const b = bind(orig, p, {});
  const usage = `<X${contentProp(p.prop, b.props)} />`;
  assert.match(usage, /form1: <><form action="\/api\/contact" method="post"/);
  assert.match(usage, /heading1: <>Talk to us<\/>/);
  assert.ok(b.carried.some((c) => c.text === 'Send message'));
  assert.ok(!p.slots.some((s) => s.demo === 'Submit'), 'nothing inside the design form is a slot');
  assert.equal(b.lost, undefined);
});

test('forms: a design with no place for the owner\'s form is not offered (a newsletter would lose its email field)', () => {
  const news = `export function N() { return (<section><h2>Cleaning tips, once a month</h2><p>No spam.</p>
    <form className="flex gap-2"><Input type="email" placeholder="you@company.com" /><Button type="submit">Subscribe</Button></form></section>); }`;
  const { b } = swap(unitsAt(news, '<section'), CTA, { forms: 'swap' });
  assert.equal(b.lost, 'form');
  assert.match(noVariantsWhy([{ id: 'a', why: 'POOR_FIT', detail: 'has no place for your form' }], 'cta'), /has a place for your form/);
});

/* ------------------------------------------------------------------ cards and buttons (UI primitives) */

const ONE_CARD = `export function C() { return (<div className="rounded-xl border p-6"><h3 className="font-semibold">Office cleaning</h3><p className="text-sm">Desks, kitchens and meeting rooms, every night.</p></div>); }`;

test('a card whose words are its props\' defaults gets the owner\'s words AS those props; the ones left are emptied', () => {
  const design = `export default function CardFlip({
  title = "Design Systems",
  subtitle = "Explore the fundamentals",
  description = "Dive deep into the world of modern UI/UX design.",
  features = ["UI/UX", "Modern Design", "Tailwind CSS"],
}: CardFlipProps) {
  return (
    <div className="group relative h-[320px]">
      <style>{\`@keyframes scale { 0% { transform: scale(1); } 100% { transform: scale(1.1); } }\`}</style>
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="text-sm">{subtitle}</p>
      <p className="text-sm">{description}</p>
      <ul>{features.map((feature) => <li key={feature}>{feature}</li>)}</ul>
      <button type="button">Start today</button>
    </div>
  );
}`;
  const orig = unitsAt(ONE_CARD, '<div');
  const { p, b, usage } = swap(orig, design);
  assert.ok(!p.slots.some((s) => /keyframes/.test(s.demo || '')), 'a <style> block is not text');
  assert.match(usage, /title=\{"Office cleaning"\}/);
  assert.match(usage, /subtitle=\{"Desks, kitchens and meeting rooms, every night\."\}/);
  assert.match(usage, /description=\{""\}/);
  assert.match(usage, /features=\{\[\]\}/);
  assert.match(usage, /content=\{\{ action1Show: false \}\}/);
  assert.equal(b.carried.length, 2);
});

test('a button whose label is a prop (`label = "Welcome"`) shows the owner\'s button text', () => {
  const design = `export default function GradientButton({ label = "Welcome", className, ...props }: Props) {
  return <button className={className} {...props}><span className="relative z-10">{label}</span></button>;
}`;
  const orig = unitsAt('export function B() { return (<div><Button size="sm">Add to cart</Button></div>); }', '<Button');
  const { usage } = swap(orig, design);
  assert.equal(usage, '<X label={"Add to cart"} />');
});

test('only a design that shows nothing put inside it goes through the transplant; a wrapper keeps the owner\'s content', () => {
  assert.equal(rendersChildren('c.tsx', 'export function Card({ className, children }) { return <div className={className}>{children}</div> }', { kind: 'named', name: 'Card' }), true);
  assert.equal(rendersChildren('c.tsx', 'export default function N({ className, ...props }) { return <div className={className} {...props} /> }', { kind: 'default' }), true);
  // a button (or a <p>) takes the owner's words only — never their card's divs (invalid HTML: hydration errors)
  assert.equal(rendersChildren('c.tsx', 'const X = React.forwardRef((props, ref) => <button ref={ref} {...props} />); export default X', { kind: 'default' }), 'inline');
  assert.equal(rendersChildren('c.tsx', 'export default function M({ children, subtitle }) { return <div><h2>Acme</h2><p className="t">{children || subtitle}</p></div> }', { kind: 'default' }), 'inline');
  assert.equal(rendersChildren('c.tsx', 'export default function CardFlip({ title = "Design" }) { return <div><h3>{title}</h3></div> }', { kind: 'default' }), false);
});

/* ------------------------------------------------------------------ cards in rows (blog, services) */

const BLOG = `const posts = [
  { title: "How often should an office be deep-cleaned?", excerpt: "A simple schedule by team size and foot traffic.", date: "12 Sep 2026", tag: "Guides", href: "/blog/a", img: "/window.svg" },
  { title: "Eco products that actually work", excerpt: "What we switched to in 2025 and what we dropped.", date: "28 Aug 2026", tag: "Behind the scenes", href: "/blog/b", img: "/globe.svg" },
  { title: "Your first week with us", excerpt: "From the walkthrough to the first photo report.", date: "3 Aug 2026", tag: "Clients", href: "/blog/c", img: "/file.svg" },
];
export function BlogCards() {
  return (
    <section>
      <h2 className="text-3xl font-semibold">From the blog</h2>
      <div className="grid md:grid-cols-3">
        {posts.map((p) => (
          <article key={p.href}>
            <img src={p.img} alt={p.title} />
            <p className="text-xs">{p.date} · {p.tag}</p>
            <h3 className="font-semibold">{p.title}</h3>
            <p className="text-sm">{p.excerpt}</p>
            <Link href={p.href}>Read more</Link>
          </article>
        ))}
      </div>
    </section>
  );
}`;

test('blog cards: the title goes to the card title and the excerpt to its text — never the "12 Sep · Guides" line', () => {
  const design = `export default function Features() { return (<section><h2>Built for scale</h2><div className="grid grid-cols-3">
    <div><h3>Fast</h3><p>Everything loads instantly for every member of the team.</p></div>
    <div><h3>Secure</h3><p>Encryption at rest and in transit, with audit logs.</p></div>
    <div><h3>Flexible</h3><p>Adapts to how your team already works every day.</p></div></div></section>) }`;
  const orig = unitsAt(BLOG, '<section');
  assert.equal(contentCount(orig), 3 * 4 + 1 + 3, 'every card\'s image counts');
  const { usage, b } = swap(orig, design);
  assert.match(usage, /heading2: <>How often should an office be deep-cleaned\?<\/>, text1: <>A simple schedule by team size and foot traffic\.<\/>/);
  assert.ok(!/12 Sep 2026/.test(usage));
  assert.ok(b.dropped.some((d) => /12 Sep 2026/.test(d.text)));
});

test('a plan list with a demo feature list: the owner\'s items without bullets get none of the design\'s', () => {
  const PRODUCTS = `const products = [
  { name: "Microfiber kit", price: "€24", img: "/window.svg" },
  { name: "Eco floor cleaner", price: "€9", img: "/globe.svg" },
];
export function P() { return (<section><h2>Shop</h2><div className="grid">{products.map((p) => (
  <div key={p.name}><img src={p.img} alt={p.name} /><h3>{p.name}</h3><p>{p.price}</p><Button>Add to cart</Button></div>
))}</div></section>); }`;
  const design = `const plans = [
  { name: 'Basic', price: '$9', features: ['1 user', '5 projects'] },
  { name: 'Pro', price: '$29', features: ['5 users', 'Unlimited projects'] },
]
export default function Pricing() { return (<section><h2>Pricing</h2>{plans.map((plan) => (
  <div key={plan.name}><h3>{plan.name}</h3><span>{plan.price}</span><ul>{plan.features.map((f) => <li key={f}>{f}</li>)}</ul></div>
))}</section>) }`;
  const { usage } = swap(unitsAt(PRODUCTS, '<section'), design);
  assert.match(usage, /"name": "Microfiber kit", "price": "€24", "features": \[\]/);
});

/* ------------------------------------------------------------------ honesty marks, loading, catalog */

test('every word a design still shows of its own is marked demo (dashed): constant text and an illustration\'s data rows', () => {
  const code = `const rows = [{ customer: 'Acme', revenue: '$1,200' }]
export default function F({ content = {} }) {
  return (
    <section>
      <h2>{content.heading1 ?? <span data-dh-demo="">Demo title</span>}</h2>
      <p className="text-sm">Don't have an account?</p>
      <table><tbody>{rows.map((r) => <tr key={r.customer}><td>{r.customer}</td><td>{r.revenue}</td></tr>)}</tbody></table>
    </section>
  )
}`;
  const out = markDemo('f.tsx', code);
  assert.match(out, /<p data-dh-demo="" className="text-sm">Don't have an account\?<\/p>/);
  assert.match(out, /<td data-dh-demo="">\{r\.customer\}<\/td>/);
  assert.ok(!/<h2 data-dh-demo/.test(out), 'the owner\'s slot is not marked');
  assert.doesNotThrow(() => parse('f.tsx', out));
});

test('a design file with a TypeScript function type loads (it used to crash the fix-up pass: FETCH errors)', () => {
  const code = `interface Props { onChange?: (value: string) => void; label?: string }
type Handler = (e: MouseEvent) => void
export default function X({ onChange, label = 'Go' }: Props) { return <button onClick={() => onChange?.('x')}>{label}</button> }`;
  assert.doesNotThrow(() => compatFixes('x.tsx', code));
});

test('catalog: a tweet embed is not a card, a hover card is a popover, a vendor\'s branded button is not offered', () => {
  assert.equal(slotFromName('tweet-card'), 'embed');
  assert.equal(slotFromName('client-tweet-card'), 'embed');
  assert.equal(slotFromName('hover-card'), 'popover');
  assert.equal(slotFromName('glow-hover-card'), 'popover');
  assert.equal(slotFromName('v0-button'), null);
  assert.equal(slotFromName('gradient-button'), 'button');
  assert.equal(slotFromName('card-flip'), 'card');
});

test('no variants: the owner reads why in plain words, with the closest fit', () => {
  const msg = noVariantsWhy([{ id: 'a', why: 'POOR_FIT', detail: 'carries 1/9' }, { id: 'b', why: 'POOR_FIT', detail: 'carries 3/9' }, { id: 'c', why: 'FETCH_FAILED' }], 'integrations');
  assert.match(msg, /none of the 2 integrations design\(s\) has room for your content \(the closest keeps 3 of your 9 pieces\)/);
  assert.match(noVariantsWhy([{ id: 'c', why: 'FETCH_FAILED' }], 'hero'), /could not be downloaded/);
});

/* ------------------------------------------------------------------ product cards into plan designs */

const SHOP = `const products = [
  { name: "Microfiber kit", price: "€24", note: "12 cloths, colour-coded" },
  { name: "Eco floor cleaner", price: "€9", note: "1 L, lavender" },
  { name: "Starter bundle", price: "€59", note: "Everything for a small office" },
];
export function Shop() {
  return (
    <section>
      <h2 className="text-3xl font-semibold">Shop our supplies</h2>
      <div className="grid grid-cols-3">
        {products.map((p) => (
          <div key={p.name}><h3>{p.name}</h3><p>{p.note}</p><p className="font-bold">{p.price}</p><Button size="sm">Add to cart</Button></div>
        ))}
      </div>
    </section>
  );
}`;

test('a featured card\'s extra badge ("Popular") never takes the product name — every word stays in its place', () => {
  const design = `export default function Pricing() { return (<section><h2>Start free.</h2><div className="grid grid-cols-3">
    <div className="card"><h3 className="name">Starter</h3><p className="desc">For solo developers</p><span className="price">$0 /mo</span><Button>Get Started</Button></div>
    <div className="card"><span className="badge">Popular</span><h3 className="name">Pro</h3><p className="desc">For ambitious founders</p><span className="price">$59 /mo</span><Button>Get Started</Button></div>
    <div className="card"><h3 className="name">Startup</h3><p className="desc">For growing teams</p><span className="price">$99 /mo</span><Button>Get Started</Button></div>
  </div></section>) }`;
  const { p, usage } = swap(unitsAt(SHOP, '<section'), design);
  const badge = p.slots.find((x) => x.demo === 'Popular');
  assert.ok(badge.optional, 'the badge is an extra of the featured card');
  assert.match(p.code, new RegExp(`\\{content\\.${badge.key} !== false && \\(<span className="badge">`), 'hidden whole when unfilled');
  assert.match(usage, new RegExp(`${badge.key}: false`));
  assert.match(usage, /<>Eco floor cleaner<\/>, text\d+: <>1 L, lavender<\/>/);
});

test('a plan template\'s own button label becomes a field: the owner\'s "Add to cart" — and no "/month" on a product', () => {
  const design = `const tiers = [
  { name: 'Hobby', description: 'For personal projects', price: '$0', period: '/month' },
  { name: 'Pro', description: 'For small teams', price: '$29', period: '/month' },
]
export default function Pricing() {
  return (<section><h2>Usage-Based Pricing</h2>{tiers.map((tier) => (
    <Card key={tier.name}>
      <h3>{tier.name}</h3><p>{tier.description}</p>
      <span>{tier.price}</span>{tier.period && <span className="text-sm">{tier.period}</span>}
      <Button asChild><Link href="#link">{tier.price === 'Custom' ? 'Contact Us' : 'Get Started'}<ArrowRight /></Link></Button>
    </Card>
  ))}</section>)
}`;
  const { p, b, usage } = swap(unitsAt(SHOP, '<section'), design);
  assert.match(p.code, /\{\(tier as any\)\.dhAction \?\? <span data-dh-demo="">\{tier\.price === 'Custom' \? 'Contact Us' : 'Get Started'\}<\/span>\}/);
  assert.match(usage, /"name": "Microfiber kit", "description": "12 cloths, colour-coded", "price": "€24", "dhAction": "Add to cart"/);
  assert.match(usage, /"period": ""/);
  assert.ok(!b.dropped.some((d) => d.text === 'Add to cart'));
  assert.doesNotThrow(() => parse('c.tsx', p.code));
});

test('a label that switches with a state (`{hover ? "Attracting" : "Hover me"}`) is a slot; a spread with children of its own is not a wrapper', () => {
  const design = `export default function AttractButton({ className, attractRadius = 50, ...props }: Props) {
  const [on, setOn] = useState(false);
  return (
    <Button className={className} {...props}>
      <span className="relative flex gap-2"><Magnet className="h-4 w-4" />{on ? "Attracting" : "Hover me"}</span>
    </Button>
  );
}`;
  assert.equal(rendersChildren('c.tsx', design, { kind: 'default' }), false);
  const orig = unitsAt('export function B() { return (<div><Button size="sm">Add to cart</Button></div>); }', '<Button');
  const { p, usage } = swap(orig, design);
  assert.deepEqual(p.slots.map((x) => [x.role, x.demo]), [['action', 'Hover me']]);
  assert.equal(usage, '<X content={{ action1: <>Add to cart</> }} />');
  assert.match(p.code, /\{content\.action1 \?\? <span data-dh-demo="">\{on \? "Attracting" : "Hover me"\}<\/span>\}/);
});

test('demo words inside a component get a marked span of their own; Keep unwraps it and strips every mark', () => {
  const code = `export default function F() { return (<section><Button asChild><Link href="#">Get Started</Link></Button><span className="t">0:45</span></section>) }`;
  const marked = markDemo('f.tsx', code);
  assert.match(marked, /<Link href="#"><span data-dh-demo="" data-dh-wrap="">Get Started<\/span><\/Link>/);
  assert.match(marked, /<span data-dh-demo="" className="t">0:45<\/span>/, 'a demo player\'s "0:45" is demo too');
  assert.equal(unmarkDemo(marked), code);
});

test('fit gate: a section keeps half of the owner\'s pieces; a card or a button all of them; any design their form', () => {
  const b = (n, extra = {}) => ({ carried: Array.from({ length: n }, () => ({})), ...extra });
  assert.equal(fitGate('block', 16, b(8)), null);
  assert.equal(fitGate('block', 16, b(7)), 'carries 7/16');
  assert.equal(fitGate('ui', 2, b(1)), 'carries 1/2', 'a fitness-rings "card" that drops the title is not offered');
  assert.equal(fitGate('ui', 2, b(2)), null);
  assert.equal(fitGate('ui', 1, b(0)), 'carries 0/1', 'a button that shows none of the label');
  assert.equal(fitGate('block', 5, b(5, { lost: 'form' })), 'has no place for your form');
});

test('a design\'s `<Card variant="outline">` against the project\'s own Card (no variants) is fitted, so Keep passes `next build`', () => {
  const dir = tempSite();
  fs.writeFileSync(path.join(dir, 'components/ui/card.tsx'), `import * as React from "react"
function Card({ className, ...props }: React.ComponentProps<"div">) { return <div className={className} {...props} /> }
export { Card }
`);
  const prof = detectProject(dir);
  const design = `import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
export default function P() {
  return (<Card variant="outline" className="p-4"><Button variant="neutral" size="sm">Go</Button><Button variant={on ? 'default' : 'outline'}>Two</Button></Card>)
}`;
  const out = fitProjectPrimitives(prof, 'p.tsx', design);
  assert.match(out, /<Card className="p-4">/, 'a prop the project\'s Card does not take is dropped');
  assert.match(out, /<Button variant="default" size="sm">Go<\/Button>/, 'a value the project\'s Button does not have becomes "default"');
  assert.match(out, /variant=\{on \? 'default' : 'outline'\}/, 'values it has stay');
});

test('overlay on a phone: the bar wraps (every button reachable, the design\'s name on its own row); the page is not a section', () => {
  const src = fs.readFileSync(new URL('../overlay.js', import.meta.url), 'utf8');
  assert.match(src, /@media \(max-width:640px\)\{\.bar\{[^}]*flex-wrap:wrap[^}]*\}\.bar \.meta\{order:-1;flex:1 1 100%/);
  assert.match(src, /if \(t === 'body' \|\| t === 'html' \|\| t === 'main'\) return null;/, 'no "signup — body" crumb because a login form is somewhere on the page');
});

test('a wrapper card keeps the owner\'s content inside, and its own prop words ("Acme", "Case Study") are emptied', async () => {
  const { defaultPropsOf } = await import('../lib/transplant.mjs');
  const design = `export default function MouseEffectCard({ children, title = "Acme", topText = "Case Study", primaryCtaText = "Get Started", subtitle }: Props) {
  return (<div><span>{topText}</span><h2>{title}</h2><div>{children || subtitle}</div><button>{primaryCtaText}</button></div>);
}`;
  assert.equal(rendersChildren('c.tsx', design, { kind: 'default' }), true);
  assert.deepEqual(defaultPropsOf('c.tsx', design, { kind: 'default' }).map((d) => [d.propName, d.role]), [['title', 'heading'], ['topText', 'text'], ['primaryCtaText', 'action']]);
  // a fallback after what is passed in is a slot too: `{children || subtitle}` shows the demo subtitle otherwise
  const withSub = design.replace('subtitle }', 'subtitle = "Build interfaces with interactive patterns" }');
  assert.ok(defaultPropsOf('c.tsx', withSub, { kind: 'default' }).some((d) => d.propName === 'subtitle'));
});

test('a button prop and the link prop it sits in (`<a href={primaryCtaUrl}>{primaryCtaText}</a>`): the owner\'s text AND link', () => {
  const design = `export default function M({ title = "Acme", primaryCtaText = "Get Started", primaryCtaUrl = "#" }: Props) {
  return (<div><h2>{title}</h2><a href={primaryCtaUrl} className="btn">{primaryCtaText}</a></div>);
}`;
  const orig = unitsAt('export function C() { return (<div className="card"><h3>Free walkthrough</h3><Button asChild><Link href="/quote">Book a walkthrough</Link></Button></div>); }', '<div');
  const { usage } = swap(orig, design);
  assert.equal(usage, '<X title={"Free walkthrough"} primaryCtaText={"Book a walkthrough"} primaryCtaUrl={"/quote"} />');
});
