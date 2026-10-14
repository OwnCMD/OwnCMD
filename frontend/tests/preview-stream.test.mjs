import test from 'node:test';
import assert from 'node:assert/strict';
import {FrameDecoder} from '../lib/preview-stream.mjs';
function packet(bytes,seq=1){const h=new TextEncoder().encode(JSON.stringify({length:bytes.length,seq}));const b=new Uint8Array(4+h.length+bytes.length);new DataView(b.buffer).setUint32(0,h.length);b.set(h,4);b.set(bytes,4+h.length);return b;}
test('binary preview handles every possible network split and heartbeats',()=>{
 const frame=packet(new Uint8Array([255,216,0,255,217]));
 for(let split=0;split<=frame.length;split++){
  const got=[];const d=new FrameDecoder((m,b)=>got.push([m,b]));d.push(frame.slice(0,split));d.push(frame.slice(split));d.push(packet(new Uint8Array(),2));d.finish();
  assert.equal(got.length,2);assert.deepEqual([...got[0][1]],[255,216,0,255,217]);assert.equal(got[1][1],null);
 }
});
test('combined large network chunks do not accumulate historical frames',()=>{
 let got=0;const d=new FrameDecoder(()=>got++);const p=packet(new Uint8Array(100000));const batch=new Uint8Array(p.length*20);
 for(let i=0;i<20;i++)batch.set(p,i*p.length);
 d.push(batch);d.finish();assert.equal(got,20);assert.equal(d.buffer.length,0);
});
test('malformed, oversized and truncated frame data are rejected',()=>{
 const d=new FrameDecoder(()=>{});assert.throws(()=>d.push(new Uint8Array([255,255,255,255])));
 const short=new FrameDecoder(()=>{});short.push(packet(new Uint8Array([1,2])).slice(0,-1));assert.throws(()=>short.finish());
 for(const length of [-1,5000000,'12',null]){
  const h=new TextEncoder().encode(JSON.stringify({length}));const b=new Uint8Array(4+h.length);new DataView(b.buffer).setUint32(0,h.length);b.set(h,4);
  assert.throws(()=>new FrameDecoder(()=>{}).push(b));
 }
});
