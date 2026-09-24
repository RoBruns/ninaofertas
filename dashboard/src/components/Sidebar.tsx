import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'

const items = [
  ['/', 'Visão geral', '◦'], ['/bots', 'Bots', '◉'], ['/contas', 'Contas', '▣'],
  ['/telefones', 'Telefones e grupos', '◫'], ['/vendas', 'Vendas', '◈'],
  ['/despesas', 'Despesas', '◒'], ['/campanhas', 'Campanhas', '◎'], ['/alertas', 'Alertas', '△'],
  ['/logs', 'Logs técnicos', '≡'], ['/auditoria', 'Auditoria', '⌕'], ['/usuarios', 'Usuários', '♙'],
] as const

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth()
  const adminOnly = new Set(['/auditoria', '/usuarios'])
  return <><button className={`sidebar-backdrop ${open ? 'open' : ''}`} aria-label="Fechar menu" onClick={onClose} /><aside className={`sidebar ${open ? 'open' : ''}`}><div className="brand"><span>N</span><div><strong>Nina</strong><small>Ofertas</small></div></div><nav aria-label="Navegação principal">{items.filter(([path]) => !adminOnly.has(path) || user?.role === 'admin').map(([path, label, icon]) => <NavLink key={path} to={path} end={path === '/'} onClick={onClose}><span aria-hidden="true">{icon}</span>{label}</NavLink>)}</nav></aside></>
}
