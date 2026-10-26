export function key():string;
export function money(value:unknown,currency?:string):string;
export function percent(value:unknown):string;
export function curveSegments<T extends {nav:unknown}>(rows:T[]):Array<Array<T&{index:number}>>;
export function marketRows<T extends {market?:string;instrument?:{market?:string};frozen?:{source_market?:string}}>(rows:T[],market:string):T[];
export function request<T=unknown>(path:string,token:string,options?:{method?:string;body?:unknown;key?:string;signal?:AbortSignal},fetcher?:typeof fetch):Promise<T>;
