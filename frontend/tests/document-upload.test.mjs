import test from 'node:test';
import assert from 'node:assert/strict';
import {uploadDocument} from '../lib/document-upload.mjs';
test('chunks resume without sending confirmed data again',async()=>{
 const file=new Blob(['abcdefghij']);file.name='a.txt';let completed=false;const sent=[];
 const result=await uploadDocument(file,'id',{request:async(path)=>path==='attachments'?{id:'id',part_size:4}:path.endsWith('complete')?(completed=true,{id:'id',status:'queued'}):{id:'id',status:completed?'ready':'uploading',parts:[0],part_size:4},put:async(id,n,blob)=>{sent.push([n,await blob.text()]);return {id,status:'uploading',part_size:4};},onUpdate:()=>{}});
 assert.equal(result.status,'ready');assert.deepEqual(sent,[[1,'efgh'],[2,'ij']]);
});
test('ambiguous chunk failures retry the same offset exactly once',async()=>{
 let count=0;const file=new Blob(['data']);file.name='a.txt';
 await assert.rejects(uploadDocument(file,'id',{request:async()=>({id:'id',status:'uploading',part_size:4,parts:[]}),put:async()=>{count++;throw Error('offline');},onUpdate:()=>{}}),/offline/);assert.equal(count,2);
});
test('processing failure is surfaced without an endless poll',async()=>{
 const file=new Blob(['data']);file.name='a.txt';let completed=false;
 await assert.rejects(uploadDocument(file,'id',{request:async path=>path==='attachments'?{id:'id',part_size:4}:path.endsWith('complete')?(completed=true,{id:'id',status:'queued'}):{id:'id',status:completed?'failed':'processing',parts:[],info:{error:'Damaged PDF'}},put:async()=>{},onUpdate:()=>{}}),/Damaged PDF/);
});
test('archive uploads require Work mode before any network request',async()=>{
 const file=new Blob(['archive bytes']);file.name='source.RAR';let called=false;
 await assert.rejects(uploadDocument(file,'id',{request:async()=>{called=true},put:async()=>{},onUpdate:()=>{},mode:'chat'}),/Work mode/);
 assert.equal(called,false);
});
test('archive upload keeps the resumable path and sends Work mode metadata',async()=>{
 const file=new Blob(['archive bytes']);file.name='project.7z';let metadata,complete=false,sent='';
 const result=await uploadDocument(file,'id',{mode:'work',request:async(path,body)=>{
  if(path==='attachments'){metadata=body;return {id:'id',part_size:1024};}
  if(path.endsWith('/complete'))complete=true;
  return {id:'id',status:complete?'ready':'uploading',parts:[],part_size:1024,info:complete?{kind:'archive'}:{}};
 },put:async(id,n,data)=>{sent=await data.text();return {id,status:'uploading'}},onUpdate:()=>{}});
 assert.equal(metadata.mode,'work');assert.equal(metadata.name,'project.7z');assert.equal(sent,'archive bytes');assert.equal(result.info.kind,'archive');
});
