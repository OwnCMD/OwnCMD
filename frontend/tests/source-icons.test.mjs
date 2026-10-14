import test from 'node:test';
import assert from 'node:assert/strict';
import {createSourceIconStore} from '../lib/source-icons.mjs';
const flush=()=>new Promise(resolve=>setTimeout(resolve,0));
test('late same-domain metadata repairs all subscribers without repeated probes',async()=>{
 const calls=[];const store=createSourceIconStore(async url=>{calls.push(url);if(url.endsWith('favicon.ico'))throw Error('404');});
 let a='',b='';store.subscribe('docs.example.com',()=>a=store.get('docs.example.com'));store.subscribe('docs.example.com',()=>b=store.get('docs.example.com'));
 store.add([{url:'https://docs.example.com/first'}]);await flush();assert.equal(a,'');
 store.add([{url:'https://docs.example.com/second',favicon:'https://cdn.example.com/logo.svg'}]);await flush();
 assert.equal(a,b);assert.equal(a,'https://cdn.example.com/logo.svg');
 store.add([{url:'https://docs.example.com/third'}]);await flush();assert.equal(calls.length,2);
});
test('domain isolation and bounded failures',async()=>{
 const calls=[];const store=createSourceIconStore(async url=>{calls.push(url);throw Error('blocked');});
 store.subscribe('a.example.com',()=>{});store.subscribe('b.example.com',()=>{});
 const rows=[{url:'https://a.example.com/a'},{url:'https://b.example.com/a'}];store.add(rows);await flush();store.add(rows);await flush();assert.equal(calls.length,2);assert.equal(store.get('a.example.com'),'');
});
