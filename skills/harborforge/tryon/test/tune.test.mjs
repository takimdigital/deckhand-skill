import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { tempSite, read, locate } from './helpers.mjs';
import { tuneToken, tuneClassList, tuneOpen, tuneSet, tuneKeep, tuneReset, PRESETS } from '../lib/tune.mjs';
import { themeVars, themeCss, themeApply, themeUndo, themeState, rewriteFonts } from '../lib/sitetheme.mjs';
import { detectProject } from '../lib/project.mjs';

const require = createRequire(import.meta.url);
const { parse } = require('../lib/ast.cjs');
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');

test('knobs are exact class transforms (variants and ! kept, circles and non-numeric spacing left alone)', () => {
  assert.equal(tuneToken('md:py-24', { density: 1 }), 'md:py-30');
  assert.equal(tuneToken('gap-3', { density: -1 }), 'gap-2.5');
  assert.equal(tuneToken('mx-auto', { density: 2 }), 'mx-auto');
  assert.equal(tuneToken('-mt-4', { density: 2 }), '-mt-6');
  assert.equal(tuneToken('text-5xl', { size: 1 }), 'text-6xl');
  assert.equal(tuneToken('text-lg', { size: 1 }), 'text-lg');                 // body text moves half as much
  assert.equal(tuneToken('text-lg', { size: 2 }), 'text-xl');
  assert.equal(tuneToken('font-semibold', { weight: 1 }), 'font-bold');
  assert.equal(tuneToken('font-light', { weight: -2 }), 'font-light');        // clamped: never unreadable
  assert.equal(tuneToken('rounded-lg', { corners: 'sharp' }), 'rounded-none');
  assert.equal(tuneToken('rounded-full', { corners: 'round' }), 'rounded-full');
  assert.equal(tuneToken('rounded-md', { corners: 'pill' }, { control: true }), 'rounded-full');
  assert.equal(tuneToken('hover:shadow-lg', { depth: 'flat' }), 'hover:shadow-none');
  assert.equal(tuneToken('text-muted-foreground', { contrast: 'crisp' }), 'text-foreground/80');
  assert.equal(tuneToken('max-w-3xl', { width: 1 }), 'max-w-4xl');
  assert.equal(tuneClassList('rounded-xl border p-6', { depth: 'raised' }, { card: true }), 'rounded-xl border p-6 shadow-md');
  assert.deepEqual(Object.keys(PRESETS), ['quieter', 'bolder', 'airy', 'compact', 'clarity', 'softer', 'sharper']);
});

test('a tune session recomputes from the original (no drift), parses, and resets byte-exact', () => {
  const dir = tempSite();
  const before = fs.readFileSync(path.join(dir, 'components/hero.tsx'));
  const at = locate(before.toString(), '<section');
  const t = tuneOpen(dir, { file: 'components/hero.tsx', ...at });
  tuneSet(dir, t.id, { dials: { density: 2 } });
  assert.match(read(dir, 'components/hero.tsx'), /py-36/);                   // py-24 × 1.5
  tuneSet(dir, t.id, { dials: { density: 2 } });
  assert.match(read(dir, 'components/hero.tsx'), /py-36/);                   // twice = same, not py-54
  tuneSet(dir, t.id, { preset: 'bolder' });
  const bolder = read(dir, 'components/hero.tsx');
  parse('hero.tsx', bolder);
  assert.match(bolder, /text-6xl font-extrabold/);                            // text-5xl font-bold → one notch up
  assert.match(bolder, /py-24/);                                               // bolder does not touch spacing
  const r = tuneReset(dir, t.id);
  assert.equal(r.mode, 'byte-exact');
  assert.equal(sha(fs.readFileSync(path.join(dir, 'components/hero.tsx'))), sha(before));
  const t2 = tuneOpen(dir, { file: 'components/hero.tsx', ...at });
  tuneSet(dir, t2.id, { preset: 'airy' });
  assert.equal(tuneKeep(dir, t2.id).kept.density, 2);
  assert.match(read(dir, 'components/hero.tsx'), /py-36/);
});

const LAYOUT = `import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={\`\${geistSans.variable} \${geistMono.variable} h-full antialiased\`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
`;

test('site theme: exact variables, one marked block, fonts rewritten by AST, undo byte-exact', () => {
  const dir = tempSite();
  fs.writeFileSync(path.join(dir, 'app/layout.tsx'), LAYOUT);
  const v = themeVars({ accent: 'terracotta', corners: 'round', density: 'airy', headlines: 'larger', neutrals: 'warm' });
  assert.equal(v.light.primary, 'oklch(0.620 0.150 40.0)');
  assert.equal(v.light['primary-foreground'], 'oklch(0.985 0 0)');
  assert.equal(v.light.radius, '0.875rem');
  assert.equal(v.light.spacing, '0.27rem');
  assert.equal(v.light['text-4xl'], '2.52rem');
  assert.match(v.light.background, /oklch\(0\.990 0\.004 70\.0\)/);
  assert.equal(themeVars({ accent: '#b45309' }).light.primary.startsWith('oklch(0.5'), true);
  assert.equal(themeCss({}), '');

  const r = themeApply(dir, { accent: 'terracotta', corners: 'round', body: 'Manrope', heading: 'Fraunces' });
  assert.deepEqual(r.files, ['app/globals.css', 'app/layout.tsx']);
  const css = read(dir, 'app/globals.css');
  assert.equal((css.match(/dh:theme —/g) || []).length, 1);
  assert.match(css, /--primary: oklch\(0\.620 0\.150 40\.0\);/);
  assert.match(css, /font-family: var\(--font-heading\)/);
  assert.match(css, /body \{\n  font-family: var\(--font-geist-sans\), ui-sans-serif/);     // beats a hard-coded body font
  const lay = read(dir, 'app/layout.tsx');
  parse('layout.tsx', lay);
  assert.match(lay, /import \{ Fraunces, Geist_Mono, Manrope \} from "next\/font\/google";/);
  assert.match(lay, /const geistSans = Manrope\(\{/);
  assert.match(lay, /const fontHeading = Fraunces\(\{ variable: "--font-heading"/);
  assert.match(lay, /className=\{`\$\{fontHeading\.variable\} \$\{geistSans\.variable\}/);
  assert.deepEqual(themeState(dir).current, { accent: 'terracotta', corners: 'round', body: 'Manrope', heading: 'Fraunces' });
  themeApply(dir, { accent: 'ocean' });                                         // re-apply replaces the block, never stacks
  assert.equal((read(dir, 'app/globals.css').match(/dh:theme —/g) || []).length, 1);
  themeUndo(dir);
  assert.match(read(dir, 'app/globals.css'), /terracotta/);                     // one step back
});

test('undo restores the stylesheet and layout exactly as they were', () => {
  const dir = tempSite();
  fs.writeFileSync(path.join(dir, 'app/layout.tsx'), LAYOUT);
  const css0 = read(dir, 'app/globals.css');
  themeApply(dir, { accent: 'indigo', body: 'Inter', heading: 'Instrument_Serif' });
  assert.match(read(dir, 'app/layout.tsx'), /Instrument_Serif\(\{ variable: "--font-heading", subsets: \["latin"\], weight: "400" \}\)/);
  themeUndo(dir);
  assert.equal(read(dir, 'app/globals.css'), css0);
  assert.equal(read(dir, 'app/layout.tsx'), LAYOUT);
  assert.equal(rewriteFonts(detectProject(dir), {}).code.includes('Geist'), true);
});
