import type {Metadata} from 'next';
import './globals.css';
export const metadata:Metadata={title:'Blum | Research & Paper',description:'A focused workspace for reproducible research and paper portfolios.'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>;}
