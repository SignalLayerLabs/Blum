import test from 'node:test';
import assert from 'node:assert/strict';

test('unknown or non-finite alpha never renders as zero',async()=>{
  const {alphaMetric}=await import('../lib/alphaDeskView.mjs');
  assert.equal(alphaMetric(null,'%'),'—');
  assert.equal(alphaMetric(Infinity,'%'),'—');
  assert.equal(alphaMetric(-0.01,'%'),'-0.010%');
});

test('market view reads only the chosen market and preserves an absent benchmark',async()=>{
  const {alphaMarketView}=await import('../lib/alphaDeskView.mjs');
  const data={markets:{equity:{qualified_closed:100,mean_paired_excess_percent:6},forex:{qualified_closed:2,mean_paired_excess_percent:null}}};
  const fx=alphaMarketView(data,'forex');
  assert.equal(fx.qualifiedClosed,2);
  assert.equal(fx.alpha,null);
  assert.equal(fx.verdict,'INSUFFICIENT_EVIDENCE');
});
