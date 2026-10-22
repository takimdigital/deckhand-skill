import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {extractUnits,parameterize,bind} from '../lib/transplant.mjs';
import {actionLinkModes} from '../lib/materialize.mjs';
import {tempSite} from './helpers.mjs';
import fs from 'node:fs';
import path from 'node:path';
const require=createRequire(import.meta.url);const {parse,findElementAt}=require('../lib/ast.cjs');
function owner(){const code='export default function Hero(){return <section><h1>Owner</h1><a href="#start">Start here</a></section>}';const ast=parse('o.jsx',code);return extractUnits(code,findElementAt(ast,code,1,code.indexOf('<section')+1),ast);}
const candidate='export default function Hero(){return <section><h1>Demo</h1><Button className="hero-action" size="lg">Try it<Arrow/></Button></section>}';
test('a supported Radix action retains the owner destination and styling through an anchor child',()=>{
 const p=parameterize('c.tsx',candidate,{kind:'default'},{linkActions:{Button:'asChild'}});const b=bind(owner(),p);assert.equal(Object.fromEntries(b.props).action1Href,'"#start"');
 assert.match(p.code,/<Button className="hero-action" size="lg" asChild><a href=/);assert.match(p.code,/<Arrow\s*\/>/);parse('c.tsx',p.code);
});
test('Base UI render actions and plain host buttons retain real anchor destinations',()=>{
 for(const [source,modes,pattern] of [[candidate,{Button:'render'},/render=\{<a href=/],[candidate.replaceAll('Button','button'),{},/<a className="hero-action" size="lg" href=/]]){
  const p=parameterize('c.tsx',source,{kind:'default'},{linkActions:modes});assert.equal(Object.fromEntries(bind(owner(),p).props).action1Href,'"#start"');assert.match(p.code,pattern);parse('c.tsx',p.code);
 }
});
test('never counts an owner destination as carried by an unwired action or replaces existing handlers',()=>{
 const p=parameterize('c.tsx',candidate,{kind:'default'});assert.equal(bind(owner(),p).lost,'action');
 const wired=candidate.replace('<Button ', '<Button onClick={go} ');const q=parameterize('c.tsx',wired,{kind:'default'},{linkActions:{Button:'asChild'}});assert.doesNotMatch(q.code,/asChild|href=/);assert.match(q.code,/onClick=\{go\}/);assert.equal(bind(owner(),q).lost,'action');
});
test('discovers the actual imported primitive API, including aliases, without guessing from the project base',()=>{
 const root=tempSite();try{
  fs.mkdirSync(path.join(root,'components'),{recursive:true});fs.writeFileSync(path.join(root,'components/button.tsx'),'import {Slot} from "radix-ui";export function Button({asChild=false,...props}){const Comp=asChild?Slot:"button";return <Comp {...props}/>;}');
  const code='import {Button as Action} from "./button"; export default function Hero(){return <Action>Go</Action>}';
  assert.deepEqual(actionLinkModes(root,'components/hero.tsx',code),{Action:'asChild'});
  fs.writeFileSync(path.join(root,'components/button.tsx'),'import {Button as Primitive} from "@base-ui/react/button";export function Button(props){return <Primitive {...props}/>;}');assert.deepEqual(actionLinkModes(root,'components/hero.tsx',code),{Action:'render'});
  fs.writeFileSync(path.join(root,'components/button.tsx'),'export function Button(props){return <button {...props}/>}');assert.deepEqual(actionLinkModes(root,'components/hero.tsx',code),{});
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('repeated cards and data-driven action lists also refuse dropped destinations',()=>{
 const code='const rows=[{title:"One",href:"/one"},{title:"Two",href:"/two"}];export default function Hero(){return <section>{rows.map(row=><div><h3>{row.title}</h3><a href={row.href}>Choose</a></div>)}</section>}';
 const ast=parse('owner.tsx',code);const original=extractUnits(code,findElementAt(ast,code,1,code.indexOf('<section')+1),ast);
 const candidates=['export default function Hero(){return <section><div><h3>First</h3><Button>Choose</Button></div><div><h3>Second</h3><Button>Choose</Button></div></section>}', 'const plans=[{title:"First"},{title:"Second"}];export default function Hero(){return <section>{plans.map(plan=><div><h3>{plan.title}</h3><Button>Choose</Button></div>)}</section>}'];
 for(const source of candidates){const p=parameterize('candidate.tsx',source,{kind:'default'});assert.equal(bind(original,p).lost,'action');}
});
