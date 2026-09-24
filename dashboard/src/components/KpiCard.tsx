import clsx from 'clsx'
import { TrendingDown, TrendingUp } from 'lucide-react'
import { formatChange } from '../lib/format'
import { Price } from './Price'

export function KpiCard({ label, value, change, danger = false }: { label: string; value: string; change: number | null; danger?: boolean }) {
  const trend = change === null ? 'neutral' : change > 0 ? 'positive' : change < 0 ? 'negative' : 'neutral', money = /^-?R\$/.test(value)
  return <article className={clsx('kpi-card', danger && 'danger')}><p className="kpi-label">{label}</p><strong className={clsx('kpi-value', value === 'sem dados' && 'no-data')}>{money ? <Price value={value} /> : value}</strong><p className={clsx('kpi-change', trend)}>{change !== null && (change > 0 ? <TrendingUp aria-hidden="true" /> : change < 0 ? <TrendingDown aria-hidden="true" /> : null)}{change === null ? 'sem comparação' : formatChange(change)}{change !== null && <span className="sr-only"> em relação ao período anterior</span>}</p></article>
}
