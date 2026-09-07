import type {Metadata} from 'next';
import './globals.css';
import './live.css';
export const metadata:Metadata={title:'FaithBook — Novostok',description:'Votre espace de veille FaithBook : cibles, captures et archives.'};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="fr" className="dark"><head><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=Inter:wght@400;500;600&display=swap"/></head><body>{children}</body></html>}
