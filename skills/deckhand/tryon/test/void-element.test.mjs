// A design whose props are spread onto a void element (<input {...props} />) is not a wrapper: React throws
// "input is a self-closing tag" when the owner's content is put inside it. And that render error, which Next
// serves as a 500 page, must read as a build error with the readable message (never a <link> tag).
import test from 'node:test';
import assert from 'node:assert/strict';
import { rendersChildren, buildError } from '../lib/engine.mjs';

const named = { kind: 'named', name: 'Input' };

test('props spread onto <input> is not a wrapper (no children may go inside a void element)', () => {
  const code = `export function Input({ className, type, ...props }) { return <input type={type} className={className} {...props} />; }`;
  assert.equal(rendersChildren('input.tsx', code, named), false);
  const all = `export function Input(props) { return <input {...props} />; }`;
  assert.equal(rendersChildren('input.tsx', all, named), false);
});

test('props spread onto a non-void element still makes a wrapper', () => {
  const code = `export function Box({ className, ...props }) { return <div className={className} {...props} />; }`;
  assert.notEqual(rendersChildren('box.tsx', code, { kind: 'named', name: 'Box' }), false);
});

test('buildError recognises a React render error in the 500 page and returns its readable text', () => {
  const html = '<!DOCTYPE html><html id="__next_error__"><head><link rel="preload" as="script" href="/_next/x.js"/></head><body>'
    + '<template data-next-error-message="input is a self-closing tag and must neither have `children` nor use `dangerouslySetInnerHTML`." data-next-error-digest="1"></template></body></html>';
  const msg = buildError({ status: 500, text: html });
  assert.match(msg, /^input is a self-closing tag/);
  assert.doesNotMatch(msg, /</);
  // the same page inside an escaped script payload
  const esc = html.replace(/"/g, '\\"');
  assert.match(buildError({ status: 500, text: esc }), /^input is a self-closing tag/);
  assert.match(buildError({ status: 500, text: 'Error: Element type is invalid: expected a string' }), /Element type is invalid/);
  assert.equal(buildError({ status: 200, text: '<p>Hydration failed is a phrase in this blog post</p>' }), null);
});

test('culpritsOf blames the design named in the error itself, not every design the page lists', async () => {
  // found by a real-browser run on the sidebar: sidebar-09 threw "useSidebar must be used within a SidebarProvider"; the page's
  // client-module list also names sidebar-13, which renders fine, so both were dropped and the owner lost a working design
  const { culpritsOf } = await import('../lib/engine.mjs');
  const v = (slug) => ({ id: 'shadcn/' + slug.replace('shadcn-', '') + '@radix', slug, dir: 'components/dh-tryon/' + slug });
  const variants = [v('shadcn-sidebar-09'), v('shadcn-sidebar-13')];
  const page = '<template data-next-error-message="useSidebar must be used within a SidebarProvider." data-next-error-stack="Error: useSidebar must be used within a SidebarProvider.\n    at useSidebar (components/dh-tryon/shadcn-sidebar-09/sidebar.tsx:91:11)\n    at NavUser (components/dh-tryon/shadcn-sidebar-09/nav-user.tsx:12:5)"></template>'
    + '<script>self.__next_f.push([1,"3a1:I[\\"[project]/components/dh-tryon/shadcn-sidebar-13/shadcn-sidebar-13.tsx [app-client]\\"]"])</script>';
  assert.deepEqual(culpritsOf('/x', variants, page).map((x) => x.id), ['shadcn/sidebar-09@radix']);
  // no Next error attributes (a Vite or plain error text): every design named anywhere is still a suspect, as before
  assert.deepEqual(culpritsOf('/x', variants, 'Failed to resolve import from components/dh-tryon/shadcn-sidebar-13/a.tsx').map((x) => x.id), ['shadcn/sidebar-13@radix']);
});
