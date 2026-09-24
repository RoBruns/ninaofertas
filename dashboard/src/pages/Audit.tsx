import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { AuditLog } from '../api/analytics'
import { api, apiFailure } from '../api/client'
import { formatDate } from '../lib/format'

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

function Changes({ log }: { log: AuditLog }) {
  const before = log.before || {}, after = log.after || {}
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
  if (!keys.length) return <span className="muted">Sem alteração de campos registrada.</span>
  return <dl className="audit-diff">{keys.map((key) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd><del>{renderValue(before[key])}</del><span aria-hidden="true">→</span><ins>{renderValue(after[key])}</ins></dd></div>)}</dl>
}

function auditAuthor(log: AuditLog): string {
  if (!log.user_id) return 'Sistema'
  if (!log.user_email) return 'Usuário desconhecido'
  return log.user_name ? `${log.user_name} (${log.user_email})` : log.user_email
}

export function Audit() {
  const [page, setPage] = useState(1), [entityType, setEntityType] = useState(''), [from, setFrom] = useState(''), [to, setTo] = useState('')
  const logs = useQuery({ queryKey: ['audit', page, entityType, from, to], queryFn: async () => { const result = await api.GET('/api/audit-logs', { params: { query: { page, page_size: 25, sort: '-created_at', ...(entityType ? { entity_type: entityType } : {}), ...(from ? { from } : {}), ...(to ? { to } : {}) } } }); if (!result.data) throw apiFailure(result.error, result.response); return result.data }, refetchInterval: 30_000 })
  return <section><div className="page-heading"><div><p className="eyebrow">RASTREABILIDADE</p><h1>Auditoria</h1><p>Quem alterou, o quê mudou e quando.</p></div></div><section className="panel"><div className="filter-selects"><label className="filter-field"><span>Entidade</span><input value={entityType} onChange={(e) => { setEntityType(e.target.value); setPage(1) }} /></label><label className="filter-field"><span>De</span><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label><label className="filter-field"><span>Até</span><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label></div></section><div className="audit-list">{logs.data?.items.map((log) => <article className="panel audit-card" key={log.id}><header><div><strong>{log.action}</strong> em {log.entity_type} <code>{log.entity_id}</code></div><div><span>{auditAuthor(log)}</span><time>{formatDate(log.created_at)}</time></div></header><Changes log={log} /></article>)}</div><div className="pagination"><button className="button ghost" disabled={page === 1} onClick={() => setPage((value) => value - 1)}>Anterior</button><span>Página {page}</span><button className="button ghost" disabled={!logs.data || page * logs.data.page_size >= logs.data.total} onClick={() => setPage((value) => value + 1)}>Próxima</button></div></section>
}
