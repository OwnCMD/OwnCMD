import test from 'node:test';
import assert from 'node:assert/strict';
import {uniqueSources,remainingSources,sourceIcons} from '../lib/sources.mjs';
const source=(url,title='Evidence')=>({url,title});
test('sources deduplicate equivalent URLs while preserving distinct pages and queries',()=>{
 const rows=[source('https://example.com'),source('https://example.com/#part'),source('https://example.com/report'),source('https://example.com/report?q=2'),source('javascript:alert(1)'),source('#'),{}];
 assert.deepEqual(uniqueSources(rows),[rows[0],rows[2],rows[3]]);
});
test('favicon metadata is preferred with bounded origin fallback; unsafe URLs are ignored',()=>{
 const row=source('https://example.com/report');
 assert.deepEqual(sourceIcons({...row,favicon:'https://example.com/assets/icon.svg'}),['https://example.com/assets/icon.svg','https://example.com/favicon.ico']);
 assert.deepEqual(sourceIcons({...row,favicon:'javascript:alert(1)'}),['https://example.com/favicon.ico']);
 assert.deepEqual(sourceIcons({...row,favicon:'https://example.com/favicon.ico'}),['https://example.com/favicon.ico']);
});
test('Work summary excludes message citations without hiding uncited task evidence',()=>{
 const rows=[source('https://example.com/first'),source('https://example.com/second')];
 assert.deepEqual(remainingSources(rows,[{role:'assistant',sources:[source(rows[0].url+'#section')]},{role:'user',sources:[rows[1]]}]),[rows[1]]);
 assert.deepEqual(remainingSources(rows,[{role:'assistant',sources:rows}]),[]);
 assert.deepEqual(remainingSources(rows,[]),rows);
});
