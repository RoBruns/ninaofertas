import { Suspense, useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Header } from './Header'
import { Sidebar } from './Sidebar'
import { Spinner } from './Spinner'
function initialDark() { try { const saved = localStorage.getItem('nina-theme'); if (saved) return saved === 'dark' } catch { /* storage may be unavailable */ } return window.matchMedia('(prefers-color-scheme: dark)').matches }
export function Layout() {
  const [menuOpen, setMenuOpen] = useState(false), [dark, setDark] = useState(initialDark)
  useEffect(() => { document.documentElement.classList.toggle('dark', dark); try { localStorage.setItem('nina-theme', dark ? 'dark' : 'light') } catch { /* storage may be unavailable */ } }, [dark])
  return <div className="app-shell"><Sidebar open={menuOpen} onClose={() => setMenuOpen(false)} /><div className="app-column"><Header onMenu={() => setMenuOpen(true)} dark={dark} onTheme={() => setDark((value) => !value)} /><main className="content"><Suspense fallback={<Spinner label="Carregando tela" />}><Outlet /></Suspense></main></div></div>
}
