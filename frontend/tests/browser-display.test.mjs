import test from 'node:test';
import assert from 'node:assert/strict';
import {mobileClient, displaySize, previewDisplay, framePoint} from '../lib/browser-display.mjs';
test('client device detection does not turn a narrow desktop panel into a phone',()=>{
 const win={innerWidth:390,innerHeight:844,screen:{width:1440,height:900},matchMedia:()=>({matches:false})};
 assert.equal(mobileClient({userAgent:'X11 Linux',maxTouchPoints:0},win),false);
 assert.equal(mobileClient({userAgent:'iPhone',maxTouchPoints:5},win),true);
 assert.equal(mobileClient({userAgent:'Android Mobile',maxTouchPoints:5},win),true);
 assert.equal(mobileClient({userAgent:'Android',maxTouchPoints:5},win),false);
 assert.equal(mobileClient({userAgent:'Macintosh',maxTouchPoints:5},{...win,screen:{width:1024,height:1366},matchMedia:()=>({matches:true})}),false);
});
test('desktop panels retain desktop layout while phone auto and explicit overrides fit',()=>{
 assert.deepEqual(previewDisplay(440,700,'auto',false),{width:960,height:1527,mobile:false});
 assert.deepEqual(previewDisplay(390,500,'auto',true),{width:390,height:500,mobile:true});
 assert.deepEqual(previewDisplay(1440,850,'auto',false),{width:1440,height:850,mobile:false});
 assert.equal(previewDisplay(390,700,'desktop',true).width,1280);
 assert.equal(previewDisplay(390,700,'desktop',true).mobile,false);
 assert.equal(previewDisplay(1440,850,'mobile',false).width,430);
 assert.equal(previewDisplay(1440,850,'mobile',false).mobile,true);
 assert.equal(previewDisplay(0,500),null);
});
test('tall and high-resolution desktop viewers preserve their aspect ratio',()=>{
 for(const [width,height,mode] of [[440,900,'auto'],[480,900,'desktop'],[3840,2160,'auto'],[390,844,'desktop'],[480,2200,'desktop']]){
  const v=previewDisplay(width,height,mode,false);
  assert.ok(Math.abs(v.width/v.height-width/height)<0.002);
  assert.ok(v.width<=1920&&v.height<=4096);
 }
});
test('phone landscape stays mobile and geometry stays bounded',()=>{
 assert.deepEqual(displaySize(844,390,true),{width:844,height:390,mobile:true});
 assert.deepEqual(displaySize(390,600,true),{width:390,height:600,mobile:true});
 assert.deepEqual(displaySize(300,150,true),{width:320,height:240,mobile:true});
 assert.deepEqual(displaySize(3840,2400,false),{width:1920,height:1200,mobile:false});
 assert.equal(displaySize(0,600),null);
});
test('letterboxed and scaled frames map taps to remote coordinates',()=>{
 assert.deepEqual(framePoint({left:25,top:50,width:200,height:300},400,600,125,200),{x:200,y:300});
 assert.deepEqual(framePoint({left:25,top:50,width:200,height:300},400,600,0,800),{x:0,y:599});
});
