import test from 'node:test';
import assert from 'node:assert/strict';
import {money,percent,marketRows,request,key} from '../lib/view.mjs';

test('missing financial values never become zero',()=>{
 assert.equal(money(null,'USD'),'—'); assert.equal(percent(undefined),'—');
 assert.match(money('1000.50','EUR'),/1,000\.50/);
 assert.equal(percent('0'),'0.00%');
});
test('market filtering does not mix unlike sleeves',()=>{
 assert.deepEqual(marketRows([{market:'equity',id:1},{market:'forex',id:2}],'forex').map(r=>r.id),[2]);
});
test('unauthorized and unavailable responses expose actionable errors',async()=>{
 await assert.rejects(()=>request('/test','token',{},async()=>new Response(JSON.stringify({detail:'authentication_required'}),{status:401})),/authentication required/);
});
test('request never puts credentials in URL and mutation has an idempotency key',async()=>{
 let captured;
 const result=await request('/accounts','secret',{method:'POST',body:{cash:'100'}},async(url,options)=>{captured={url,options};return new Response('{"ok":true}');});
 assert.equal(result.ok,true);assert.equal(captured.url,'/api/v3/accounts');
 assert.equal(captured.options.headers.Authorization,'Bearer secret');
 assert.ok(captured.options.headers['Idempotency-Key']);
});
