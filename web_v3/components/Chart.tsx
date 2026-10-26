import type {Curve} from '../lib/types';
import {curveSegments} from '../lib/view.mjs';
export function Chart({curve,baseline=[],currency='USD'}:{curve:Curve;baseline?:Curve;currency?:string}){
 const all=[...curve,...baseline].flatMap(r=>r.nav===null?[]:[Number(r.nav)]).filter(Number.isFinite);
 if(!all.length)return <div className="empty">A complete valuation path is needed to draw this chart.</div>;
 const low=Math.min(...all),high=Math.max(...all),span=high-low||1;
 const points=(rows:Array<{nav:string|null;index:number}>,total:number)=>rows.map(r=>`${36+r.index/Math.max(1,total-1)*824},${210-(Number(r.nav)-low)/span*170}`).join(' ');
 return <figure className="chart"><svg viewBox="0 0 900 250" role="img" aria-label={`Portfolio value in ${currency}, compared with the frozen benchmark`}>
 {[0,1,2,3].map(i=><g key={i}><line x1="36" x2="860" y1={40+i*57} y2={40+i*57} stroke="currentColor" opacity=".10"/><text x="860" y={32+i*57} textAnchor="end">{(high-i*span/3).toLocaleString('en-US',{maximumFractionDigits:0})}</text></g>)}
 {curveSegments(baseline).map((segment,i)=><polyline key={'baseline:'+i} points={points(segment,baseline.length)} fill="none" stroke="#98a4b5" strokeWidth="2" strokeDasharray="6 4"/>)}
 {curveSegments(curve).map((segment,i)=><polyline key={'strategy:'+i} points={points(segment,curve.length)} fill="none" stroke="#40c7a5" strokeWidth="2.5"/>)}
 <text x="36" y="240">{curve[0]?.at.slice(0,10)}</text><text x="860" y="240" textAnchor="end">{curve.at(-1)?.at.slice(0,10)}</text>
 </svg><figcaption><span className="dot"/>Strategy NAV <span className="dot gray"/>Frozen benchmark <span className="muted">{currency} · bar-close values</span></figcaption></figure>;
}
