import test from 'node:test';
import assert from 'node:assert/strict';
import {randomId} from '../lib/id.mjs';
test('HTTP-safe UUID fallback uses secure bytes and correct version/variant',()=>{
 const value=randomId({getRandomValues:b=>{b.fill(255);return b}});
 assert.equal(value,'ffffffff-ffff-4fff-bfff-ffffffffffff');
});
test('no insecure random fallback',()=>assert.throws(()=>randomId({}),/secure random/));
