export const key=()=>globalThis.crypto.randomUUID();
const finite=value=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value));
export const money=(value,currency='USD')=>finite(value)?new Intl.NumberFormat('en-US',{style:'currency',currency,maximumFractionDigits:2}).format(Number(value)):'—';
export const percent=value=>finite(value)?`${Number(value).toFixed(2)}%`:'—';
export const marketRows=(rows,market)=>rows.filter(row=>(row.market??row.instrument?.market??row.frozen?.source_market)===market);
export async function request(path,token,options={},fetcher=globalThis.fetch){
 const headers={'Authorization':`Bearer ${token}`,'Content-Type':'application/json'};
 if(options.method&&options.method!=='GET')headers['Idempotency-Key']=options.key??key();
 const response=await fetcher(`/api/v3${path}`,{method:options.method??'GET',headers,cache:'no-store',signal:options.signal,
  ...(options.body===undefined?{}:{body:JSON.stringify(options.body)})});
 let payload;try{payload=await response.json();}catch{throw new Error(`Server response unavailable (${response.status}).`);}
 if(!response.ok)throw new Error(typeof payload.detail==='string'?payload.detail.replaceAll('_',' '):`Request rejected (${response.status}). Check the submitted fields.`);
 return payload;
}
