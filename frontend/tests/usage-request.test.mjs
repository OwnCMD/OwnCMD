import test from 'node:test';
import assert from 'node:assert/strict';
import {loadUsage} from '../lib/usage-request.mjs';
test('stalled 30-day request times out and retries with a fresh URL',async()=>{
 const paths=[],signals=[];
 const result=await loadUsage('days=30',async(path,signal)=>{paths.push(path);signals.push(signal);return paths.length===1?new Promise(()=>{}):{days:30};},{timeoutMs:10});
 assert.equal(result.days,30);assert.equal(paths.length,2);assert.notEqual(paths[0],paths[1]);assert.equal(signals[0].aborted,true);
});
test('two stalled attempts finish with an actionable error',async()=>{
 let calls=0;await assert.rejects(loadUsage('days=30',()=>{calls++;return new Promise(()=>{});},{timeoutMs:5}),/retry/i);assert.equal(calls,2);
});
test('changing filters cancels old requests without retrying',async()=>{
 const controller=new AbortController();let calls=0;
 const promise=loadUsage('days=30',()=>{calls++;controller.abort();return new Promise(()=>{});},{signal:controller.signal});
 await assert.rejects(promise,{name:'AbortError'});assert.equal(calls,1);
});
test('all periods use the same successful load path',async()=>{
 for(const params of ['days=7','days=30','days=90','days=30&start_date=2026-09-01&end_date=2026-09-28']){
  let calls=0;assert.equal(await loadUsage(params,async path=>{calls++;assert.ok(path.startsWith('usage?'+params+'&'));return 'ok';}), 'ok');assert.equal(calls,1);
 }
});
