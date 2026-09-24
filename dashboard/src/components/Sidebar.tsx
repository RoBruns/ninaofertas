import { useQuery } from '@tanstack/react-query'
import { BellRing, Bot, History, KeyRound, LayoutDashboard, Megaphone, Receipt, ScrollText, ShoppingBag, Smartphone, TrendingUp, Users } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { api, apiFailure } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { BrandMark } from './BrandMark'

const groups = [
  ['Operação', [['/', 'Visão geral', LayoutDashboard], ['/bots', 'Bots', Bot], ['/telefones', 'Telefones e grupos', Smartphone], ['/contas', 'Contas', KeyRound]]],
  ['Dinheiro', [['/desempenho', 'Desempenho', TrendingUp], ['/vendas', 'Vendas', ShoppingBag], ['/despesas', 'Despesas', Receipt], ['/campanhas', 'Campanhas', Megaphone]]],
  ['Controle', [['/alertas', 'Alertas', BellRing], ['/logs', 'Logs técnicos', ScrollText], ['/auditoria', 'Auditoria', History], ['/usuarios', 'Usuários', Users]]],
] as const

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth(), adminOnly = new Set(['/auditoria', '/usuarios'])
  const alerts = useQuery({ queryKey: ['alerts', 'sidebar-count'], queryFn: async () => { const result = await api.GET('/api/alerts', { params: { query: { status: 'open', page: 1, page_size: 1 } } }); if (!result.data) throw apiFailure(result.error, result.response); return result.data.total }, refetchInterval: 60_000 })
  return <><button className={`sidebar-backdrop ${open ? 'open' : ''}`} aria-label="Fechar menu" onClick={onClose} /><aside className={`sidebar ${open ? 'open' : ''}`}><NavLink className="brand" to="/" onClick={onClose}><BrandMark /><div><strong>Nina</strong><small>Central de ofertas</small></div></NavLink><nav aria-label="Navegação principal">{groups.map(([title, items]) => <div className="nav-group" key={title}><span>{title}</span>{items.filter(([path]) => !adminOnly.has(path) || user?.role === 'admin').map(([path, label, Icon]) => <NavLink key={path} to={path} end={path === '/'} onClick={onClose}><span className="nav-icon"><Icon /></span>{label}{path === '/alertas' && !!alerts.data && <span className="nav-count">{alerts.data}</span>}</NavLink>)}</div>)}</nav><div className="sidebar-foot">A vó achou mais uma 🔥</div></aside></>
}
