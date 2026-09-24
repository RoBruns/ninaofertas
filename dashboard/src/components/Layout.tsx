import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Header } from './Header'
import { Sidebar } from './Sidebar'

export function Layout() {
  const [menuOpen, setMenuOpen] = useState(false)
  const [dark, setDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches)
  useEffect(() => { document.documentElement.classList.toggle('dark', dark) }, [dark])
  return <div className="app-shell"><Sidebar open={menuOpen} onClose={() => setMenuOpen(false)} /><div className="app-column"><Header onMenu={() => setMenuOpen(true)} dark={dark} onTheme={() => setDark((value) => !value)} /><main className="content"><Outlet /></main></div></div>
}
