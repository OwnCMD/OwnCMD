import test from 'node:test';
import assert from 'node:assert/strict';
import {fileTree,ancestorPaths} from '../lib/file-tree.mjs';
import {formatCode} from '../lib/format-code.mjs';
test('folder hierarchy keeps identical filenames distinct and directories first',()=>{
 const tree=fileTree(['package.json','app/src/index.html','app/dist/index.html','app/src/main.jsx','app/src/index.html']);
 assert.equal(tree[0].name,'app');assert.equal(tree[1].name,'package.json');
 assert.deepEqual(tree[0].children.map(n=>n.name),['dist','src']);
 assert.equal(tree[0].children[0].children[0].path,'app/dist/index.html');
 assert.deepEqual(ancestorPaths('app/src/main.jsx'),['app','app/src']);
});
test('the reported single-line HTML becomes readable with preserved content',async()=>{
 const source='<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Aster project</title></head><body><div id="root"></div><script type="module" src="/client/main.jsx"></script></body></html>';
 const formatted=await formatCode('app/index.html',source);
 assert.ok(formatted.split('\n').length>=10);assert.match(formatted,/src="\/client\/main.jsx"/);assert.match(formatted,/\n  <head>/);assert.equal(await formatCode('app/index.html',formatted),formatted);
});
test('JSX, JSON, CSS and TypeScript format; invalid or unsupported code is never repaired silently',async()=>{
 for(const [path,code] of [['a.jsx','export default function App(){return <main><h1>Hello</h1><p>World</p></main>}'],['a.json','{"one":1,"two":{"three":3}}'],['a.css','body{margin:0;color:red}'],['a.ts','const value:{a:number}={a:1};']])assert.ok((await formatCode(path,code)).includes('\n'));
 await assert.rejects(formatCode('broken.js','const = ;'));
 await assert.rejects(formatCode('script.py','print("unchanged")'));
});
