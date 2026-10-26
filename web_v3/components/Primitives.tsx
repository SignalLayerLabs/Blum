import type {ReactNode} from 'react';
export function Panel({title,note,action,children}:{title:string;note?:string;action?:ReactNode;children:ReactNode}){return <section className="panel"><div className="panel-head"><div><h2>{title}</h2>{note&&<p>{note}</p>}</div>{action}</div>{children}</section>;}
export function Metric({label,value,note}:{label:string;value:ReactNode;note?:string}){return <div className="metric"><span>{label}</span><strong>{value}</strong>{note&&<small>{note}</small>}</div>;}
export function Badge({children}:{children:ReactNode}){return <span className="badge">{children}</span>;}
export function Empty({children}:{children:ReactNode}){return <div className="empty">{children}</div>;}
export function short(value:string){return value.slice(0,8);}
