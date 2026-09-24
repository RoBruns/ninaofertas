import clsx from 'clsx'
import { formatChange } from '../lib/format'

export function KpiCard({ label, value, change, danger = false }: { label: string; value: string; change: number | null; danger?: boolean }) {
  const trend = change === null ? 'neutral' : change > 0 ? 'positive' : change < 0 ? 'negative' : 'neutral'
  return (
    <article className={clsx('kpi-card', danger && 'danger')}>
      <p className="kpi-label">{label}</p>
      <strong className="kpi-value">{value}</strong>
      <p className={clsx('kpi-change', trend)}>
        {change !== null && <span aria-hidden="true">{change > 0 ? '↑' : change < 0 ? '↓' : '→'} </span>}
        {formatChange(change)}{change !== null && <span className="sr-only"> em relação ao período anterior</span>}
      </p>
    </article>
  )
}
