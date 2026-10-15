import test from 'node:test';
import assert from 'node:assert/strict';
import {loadAlphaWithRetry} from '../lib/alphaLoad.mjs';

test('a transient aborted read retries once and returns the actual response',async()=>{
  let calls=0,retries=0; const pauses=[]; const actual={registered_count:426};
  const result=await loadAlphaWithRetry(async()=>{if(++calls===1)throw Object.assign(new Error('aborted'),{name:'AbortError'});return actual;},
    {onRetry:()=>retries++,wait:async(ms)=>pauses.push(ms)});
  assert.equal(result,actual);assert.equal(calls,2);assert.equal(retries,1);assert.deepEqual(pauses,[1000]);
});

test('persistent gateway failures stop after two reads',async()=>{
  let calls=0;
  await assert.rejects(loadAlphaWithRetry(async()=>{calls++;throw new Error('503 Service Unavailable: BACKEND_UNAVAILABLE');},{wait:async()=>{}}),/503/);
  assert.equal(calls,2);
});

test('non-transient errors are exposed without an automatic retry',async()=>{
  for (const failure of [new Error('400 invalid request'), new TypeError('network fallback already exhausted')]) {
    let calls=0;
    await assert.rejects(loadAlphaWithRetry(async()=>{calls++;throw failure;},{wait:async()=>{throw new Error('unexpected pause');}}),(error)=>error===failure);
    assert.equal(calls,1);
  }
});

test('unmounting during the retry delay prevents another read',async()=>{
  let calls=0,active=true;
  const result=await loadAlphaWithRetry(async()=>{calls++;throw Object.assign(new Error('aborted'),{name:'AbortError'});},
    {active:()=>active,wait:async()=>{active=false;}});
  assert.equal(result,undefined);assert.equal(calls,1);
});

test('a successful read performs no retry or delay',async()=>{
  let calls=0; const actual={evidence_grade:'INSUFFICIENT_EVIDENCE'};
  const result=await loadAlphaWithRetry(async()=>{calls++;return actual;},{wait:async()=>{throw new Error('unexpected pause');}});
  assert.equal(result,actual);assert.equal(calls,1);
});
