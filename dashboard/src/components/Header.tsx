import { LogOut, Menu as MenuIcon, Moon, Sun } from 'lucide-react'
import { useAuth } from '../auth/useAuth'
import { Menu } from './Menu'
const roleNames = { admin: 'Administrador', operator: 'Operador', viewer: 'Leitor' }
export function Header({ onMenu, dark, onTheme }: { onMenu: () => void; dark: boolean; onTheme: () => void }) {
  const { user, logout } = useAuth(), name = user?.name || user?.email || 'Usuário', initials = name.split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase()
  const trigger = <button className="user-button" type="button"><span className="avatar">{initials}</span><span className="user-meta"><strong>{name}</strong><span>{user ? roleNames[user.role] : ''}</span></span></button>
  return <header className="header"><button className="icon-button mobile-menu" type="button" onClick={onMenu} aria-label="Abrir menu"><MenuIcon /></button><div className="header-spacer" /><button className="icon-button" type="button" onClick={onTheme} aria-label={dark ? 'Usar tema claro' : 'Usar tema escuro'}>{dark ? <Sun /> : <Moon />}</button><Menu label="Menu do usuário" trigger={trigger} items={[{ label: user?.email ?? '', labelOnly: true }, { label: user ? roleNames[user.role] : '', labelOnly: true }, { separator: true }, { label: 'Sair', icon: <LogOut />, onClick: () => void logout() }]} /></header>
}
