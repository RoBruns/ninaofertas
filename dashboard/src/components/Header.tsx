import { useAuth } from '../auth/useAuth'

const roleNames = { admin: 'Administrador', operator: 'Operador', viewer: 'Leitor' }

export function Header({ onMenu, dark, onTheme }: { onMenu: () => void; dark: boolean; onTheme: () => void }) {
  const { user, logout } = useAuth()
  return (
    <header className="header">
      <button className="icon-button mobile-menu" type="button" onClick={onMenu} aria-label="Abrir menu">☰</button>
      <div className="header-spacer" />
      <button className="icon-button" type="button" onClick={onTheme} aria-label={dark ? 'Usar tema claro' : 'Usar tema escuro'}>{dark ? '☀' : '☾'}</button>
      <div className="user-meta"><strong>{user?.name || user?.email}</strong><span>{user ? roleNames[user.role] : ''}</span></div>
      <button className="button ghost" type="button" onClick={() => void logout()}>Sair</button>
    </header>
  )
}
