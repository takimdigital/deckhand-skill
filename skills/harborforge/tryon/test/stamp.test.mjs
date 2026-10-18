import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { stamp, parseStamp } = require('../lib/stamp.cjs');
const { parse } = require('../lib/ast.cjs');

test('stamps host and component elements with their exact position', () => {
  const src = 'export function A() {\n  return <section className="x"><Button onClick={go}>Hi</Button></section>;\n}\n';
  const out = stamp(src, 'components/a.tsx');
  assert.equal(out.count, 2);
  assert.match(out.code, /<section data-dh="components\/a\.tsx:2:10" className="x">/);
  assert.match(out.code, /<Button data-dh="components\/a\.tsx:2:33" onClick=\{go\}>/);
  parse('a.tsx', out.code);
});

test('never touches TS generics, strings, comments or fragments', () => {
  const src = [
    'const [a] = useState<boolean | null>(null);',
    'const p: Promise<Array<string>> = x;',
    'const s = "<div>not jsx</div>"; // <span>',
    'function L<T,>(p: T) { return <><List<Item> items={p} /></>; }',
    'const m = <React.Fragment><Ctx.Provider value={1}><i /></Ctx.Provider></React.Fragment>;',
  ].join('\n');
  const out = stamp(src, 'x.tsx');
  assert.equal(out.count, 2);                              // <List<Item>> and <i>
  assert.match(out.code, /useState<boolean \| null>\(null\)/);
  assert.match(out.code, /"<div>not jsx<\/div>"/);
  assert.match(out.code, /<List<Item> data-dh="x\.tsx:4:33" items=\{p\} \/>/);
  assert.doesNotMatch(out.code, /Provider data-dh/);
  assert.doesNotMatch(out.code, /Fragment data-dh/);
  parse('x.tsx', out.code);
});

test('idempotent, and unparseable input is returned untouched', () => {
  const once = stamp('const a = <p>x</p>;', 'a.tsx').code;
  assert.equal(stamp(once, 'a.tsx').code, once);
  const broken = 'const a = <p>x</div>;';
  assert.equal(stamp(broken, 'a.tsx').code, broken);
});

test('multi-line tags and jsx in .js files', () => {
  const src = 'export default () => (\n  <a\n    href="/x"\n  >go</a>\n);';
  const out = stamp(src, 'pages/i.js');
  assert.match(out.code, /<a data-dh="pages\/i\.js:2:3"\n/);
});

test('parseStamp keeps Windows drive colons in the path', () => {
  assert.deepEqual(parseStamp('C:/w/app/page.tsx:12:5'), { file: 'C:/w/app/page.tsx', line: 12, col: 5 });
  assert.equal(parseStamp('nope'), null);
});
