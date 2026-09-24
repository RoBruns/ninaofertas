import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertOctagon, AlertTriangle, CheckCircle2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { Alert } from '../api/analytics'
import { api, apiFailure } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { EmptyState } from '../components/EmptyState'
import { StatusBadge } from '../components/Management'
import { Menu } from '../components/Menu'
import { useToast } from '../components/useToast'
import { alertDestination } from '../lib/alertDestination'
import { formatDate } from '../lib/format'
export function Alerts() {
  const [status, setStatus] = useState<'open' | 'acknowledged' | 'resolved' | ''>(''), { user } = useAuth(), queryClient = useQueryClient(), { showToast } = useToast()
  const query = useQuery({ queryKey: ['alerts', status], queryFn: async () => { const result = await api.GET('/api/alerts', { params: { query: { ...(status ? { status } : {}), page: 1, page_size: 100 } } }); if (!result.data) throw apiFailure(result.error, result.response); return [...result.data.items].sort((a, b) => a.severity === b.severity ? Date.parse(b.last_seen_at) - Date.parse(a.last_seen_at) : a.severity === 'critical' ? -1 : 1) }, refetchInterval: 30_000 })
  const action = useMutation({ mutationFn: async ({ alert, operation }: { alert: Alert; operation: 'acknowledge' | 'resolve' }) => { const result = operation === 'acknowledge' ? await api.POST('/api/alerts/{alert_id}/acknowledge', { params: { path: { alert_id: alert.id } } }) : await api.POST('/api/alerts/{alert_id}/resolve', { params: { path: { alert_id: alert.id } } }); if (!result.data) throw apiFailure(result.error, result.response) }, onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['alerts'] }); showToast('Alerta atualizado.', 'success') }, onError: (error) => showToast(error instanceof Error ? error.message : 'Falha ao atualizar.', 'error') })
  const filters = [['', 'Todos'], ['open', 'Abertos'], ['acknowledged', 'Reconhecidos'], ['resolved', 'Resolvidos']] as const
  return <section><div className="page-heading"><div><h1>Alertas</h1><p>Comece pelos críticos; cada alerta aponta para onde resolver.</p></div><div className="filter-presets" role="group" aria-label="Status">{filters.map(([value, label]) => <button type="button" className={status === value ? 'active' : ''} aria-pressed={status === value} key={value} onClick={() => setStatus(value)}>{label}</button>)}</div></div>{query.data?.length === 0 ? <EmptyState title="Nenhum alerta" description="Tudo certo por aqui. A vó segue de olho." icon={CheckCircle2} /> : <div className="alert-list">{query.data?.map((alert) => <article className={`alert-card ${alert.severity}`} key={alert.id}><span className="alert-icon">{alert.severity === 'critical' ? <AlertOctagon /> : <AlertTriangle />}</span><div><div className="alert-badges"><span className={`severity ${alert.severity}`}>{alert.severity === 'critical' ? 'Crítico' : 'Atenção'}</span><StatusBadge value={alert.status} /></div><h2>{alert.title}</h2><p>{alert.detail}</p><small>Desde {formatDate(alert.first_seen_at)}, visto pela última vez {formatDate(alert.last_seen_at)}</small></div><div className="card-actions"><Link className="button primary" to={alertDestination(alert.type)}>Resolver causa</Link>{alert.status === 'open' && user?.role !== 'viewer' && <button className="button ghost" onClick={() => action.mutate({ alert, operation: 'acknowledge' })}>Reconhecer</button>}{alert.status !== 'resolved' && user?.role === 'admin' && <Menu label="Mais ações" items={[{ label: 'Resolver manualmente', danger: true, confirm: 'Marcar este alerta como resolvido?', actionLabel: 'Resolver', onClick: () => action.mutate({ alert, operation: 'resolve' }) }]} />}</div></article>)}</div>}</section>
}
