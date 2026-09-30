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
