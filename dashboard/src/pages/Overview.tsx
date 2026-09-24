import { useQuery } from '@tanstack/react-query'
import { useEffect, useState, type Dispatch, type SetStateAction } from 'react'
import { Link } from 'react-router-dom'
import { AlertOctagon, AlertTriangle } from 'lucide-react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { dimensionLabels, granularityFor, type MetricDimension, type MetricFilters, type TimeseriesResponse } from '../api/analytics'
import { api, apiFailure } from '../api/client'
import { GlobalFilters } from '../components/GlobalFilters'
import { DataWarnings } from '../components/DataWarnings'
import { useMetricFilters } from '../components/useMetricFilters'
import { KpiCard } from '../components/KpiCard'
import { Price } from '../components/Price'
import { Spinner } from '../components/Spinner'
import { formatBRL, formatCount, formatPercent, formatRatio, isNegativeMoney } from '../lib/format'
import { alertDestination } from '../lib/alertDestination'
import { compareDecimalStrings } from '../lib/moneyInput'

async function loadOverview(filters: MetricFilters) {
  const result = await api.GET('/api/metrics/overview', { params: { query: filters } })
  if (!result.data) throw apiFailure(result.error, result.response)
  return result.data
}

async function loadTimeseries(metric: string, filters: MetricFilters) {
  const result = await api.GET('/api/metrics/timeseries', { params: { query: { ...filters, metric, granularity: granularityFor(filters.from, filters.to) } } })
  if (!result.data) throw apiFailure(result.error, result.response)
  return result.data
}

function MoneyChart({ commission, spend }: { commission?: TimeseriesResponse; spend?: TimeseriesResponse }) {
  const rows = new Map<string, { date: string; commission: number | null; spend: number | null; commissionRaw: string | null; spendRaw: string | null }>()
  commission?.points.forEach((point) => rows.set(point.date, { date: point.date, commission: point.value === null ? null : Number(point.value), spend: null, commissionRaw: point.value === null ? null : String(point.value), spendRaw: null }))
  spend?.points.forEach((point) => {
    const row = rows.get(point.date) || { date: point.date, commission: null, spend: null, commissionRaw: null, spendRaw: null }
    row.spend = point.value === null ? null : Number(point.value)
    row.spendRaw = point.value === null ? null : String(point.value)
    rows.set(point.date, row)
  })
  const data = [...rows.values()].sort((a, b) => a.date.localeCompare(b.date))
  if (!data.some((row) => row.commission !== null || row.spend !== null)) return <div className="chart-empty">Sem comissão nem investimento neste período.</div>
  return <div className="chart-wrap"><ResponsiveContainer width="100%" height={310}><LineChart data={data} margin={{ top: 10, right: 12, left: 4, bottom: 5 }}><CartesianGrid strokeDasharray="3 3" opacity={0.18} /><XAxis dataKey="date" tickFormatter={(value: string) => value.split('-').slice(1).reverse().join('/')} /><YAxis tickFormatter={(value: number) => `R$ ${value}`} width={72} /><Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 10 }} formatter={(_value, name, item) => [formatBRL(name === 'Comissão' ? item.payload.commissionRaw : item.payload.spendRaw), name]} /><Legend /><Line type="monotone" name="Comissão" dataKey="commission" stroke="#2A9D6A" strokeWidth={3} connectNulls={false} /><Line type="monotone" name="Investimento" dataKey="spend" stroke="#6C74C9" strokeWidth={3} connectNulls={false} /></LineChart></ResponsiveContainer></div>
}

function Funnel({ filters, onWarnings }: { filters: MetricFilters; onWarnings: Dispatch<SetStateAction<string[]>> }) {
  const query = useQuery({ queryKey: ['metrics', 'funnel', filters], queryFn: async () => { const result = await api.GET('/api/metrics/funnel', { params: { query: filters } }); if (!result.data) throw apiFailure(result.error, result.response); return result.data }, refetchInterval: 30_000 })
  useEffect(() => { if (query.data) onWarnings(query.data.warnings) }, [onWarnings, query.data])
  if (!query.data) return <Spinner label="Carregando funil" />
  const stages = [['Envios', query.data.sends], ['Cliques', query.data.clicks], ['Pedidos', query.data.orders], ['Compradores', query.data.buyers]] as const
  const maximum = Math.max(1, ...stages.flatMap(([, value]) => value === null ? [] : [value]))
  return <div className="funnel" aria-label="Funil de conversão">{stages.map(([label, value]) => <div className="funnel-stage" key={label}><strong>{label}</strong><div className="funnel-track"><div style={{ width: value === null ? '100%' : `${Math.max(16, value / maximum * 100)}%` }} className={`funnel-bar${value === null ? ' missing' : ''}`}>{value === null ? 'sem dados' : formatCount(value)}</div></div></div>)}</div>
}

function LossTable({ filters, onWarnings }: { filters: MetricFilters; onWarnings: Dispatch<SetStateAction<string[]>> }) {
  const [dimension, setDimension] = useState<MetricDimension>('bot')
  const { update } = useMetricFilters()
  const query = useQuery({ queryKey: ['metrics', 'losses', dimension, filters], queryFn: async () => {
    const queryParams = { ...filters, sort: 'profit' }
    const result = dimension === 'platform' ? await api.GET('/api/metrics/by-platform', { params: { query: queryParams } })
      : dimension === 'account' ? await api.GET('/api/metrics/by-account', { params: { query: queryParams } })
        : dimension === 'bot' ? await api.GET('/api/metrics/by-bot', { params: { query: queryParams } })
          : dimension === 'group' ? await api.GET('/api/metrics/by-group', { params: { query: queryParams } })
            : dimension === 'campaign' ? await api.GET('/api/metrics/by-campaign', { params: { query: queryParams } })
              : await api.GET('/api/metrics/by-niche', { params: { query: queryParams } })
    if (!result.data) throw apiFailure(result.error, result.response)
    return result.data
  }, refetchInterval: 30_000 })
  useEffect(() => { if (query.data) onWarnings(query.data.warnings) }, [onWarnings, query.data])
  const items = [...(query.data?.items || [])].sort((a, b) => a.profit === null ? 1 : b.profit === null ? -1 : compareDecimalStrings(a.profit, b.profit))
  const apply = (id: string | number) => update({ [`${dimension}_id`]: String(id) })
  return <section className="panel"><div className="section-heading"><div><h2>Onde estou perdendo dinheiro</h2><p>Do menor lucro para o maior. Selecione uma linha para investigar.</p></div><label className="filter-field"><span>Comparar por</span><select aria-label="Comparar por" value={dimension} onChange={(event) => setDimension(event.target.value as MetricDimension)}>{Object.entries(dimensionLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label></div><div className="responsive-table"><table><thead><tr><th>{dimensionLabels[dimension]}</th><th>Comissão</th><th>Investimento</th><th>Lucro</th><th>ROI</th></tr></thead><tbody>{items.map((item) => <tr className="clickable-row" tabIndex={0} onClick={() => apply(item.id)} onKeyDown={(event) => { if (event.key === 'Enter') apply(item.id) }} key={item.id}><td data-label={dimensionLabels[dimension]}>{item.name}</td><td data-label="Comissão">{formatBRL(item.commission)}</td><td data-label="Investimento">{formatBRL(item.spend)}</td><td data-label="Lucro" className={isNegativeMoney(item.profit) ? 'negative-money' : ''}>{formatBRL(item.profit)}</td><td data-label="ROI">{formatPercent(item.roi)}</td></tr>)}</tbody></table></div></section>
}

export function Overview() {
  const { filters } = useMetricFilters()
  const [funnelWarnings, setFunnelWarnings] = useState<string[]>([]), [lossWarnings, setLossWarnings] = useState<string[]>([])
  const overview = useQuery({ queryKey: ['metrics', 'overview', filters], queryFn: () => loadOverview(filters), refetchInterval: 30_000 })
  const commission = useQuery({ queryKey: ['metrics', 'timeseries', 'commission', filters], queryFn: () => loadTimeseries('commission', filters), refetchInterval: 30_000 })
  const spend = useQuery({ queryKey: ['metrics', 'timeseries', 'spend', filters], queryFn: () => loadTimeseries('spend', filters), refetchInterval: 30_000 })
  const alerts = useQuery({ queryKey: ['alerts', 'overview'], queryFn: async () => { const result = await api.GET('/api/alerts', { params: { query: { status: 'open', page: 1, page_size: 5 } } }); if (!result.data) throw apiFailure(result.error, result.response); return [...result.data.items].sort((a, b) => a.severity === b.severity ? 0 : a.severity === 'critical' ? -1 : 1) }, refetchInterval: 30_000 })
  if (overview.isPending) return <><GlobalFilters /><Spinner label="Carregando indicadores" /></>
  if (overview.isError) return <section className="page-error" role="alert"><h2>Não foi possível carregar a visão geral</h2><p>{overview.error.message}</p><button className="button primary" onClick={() => void overview.refetch()}>Tentar novamente</button></section>
  const { kpis, warnings, period } = overview.data
  const moneyCards = [
    ['Faturamento', formatBRL(kpis.revenue.value), kpis.revenue.change_pct, false], ['Comissão', formatBRL(kpis.commission.value), kpis.commission.change_pct, false],
    ['Comissão pendente', formatBRL(kpis.commission_pending.value), kpis.commission_pending.change_pct, false], ['Investimento', formatBRL(kpis.spend.value), kpis.spend.change_pct, false],
  ] as const
  const ratioCards = [
    ['ROI', formatPercent(kpis.roi.value), kpis.roi.change_pct, false],
    ['ROAS', formatRatio(kpis.roas.value), kpis.roas.change_pct, false], ['Custo por venda', formatBRL(kpis.cost_per_sale.value), kpis.cost_per_sale.change_pct, false],
    ['Custo por comprador', formatBRL(kpis.cost_per_buyer.value), kpis.cost_per_buyer.change_pct, false], ['Pedidos', formatCount(kpis.orders.value), kpis.orders.change_pct, false],
  ] as const
  const allWarnings = [...warnings, ...(commission.data?.warnings || []), ...(spend.data?.warnings || []), ...funnelWarnings, ...lossWarnings]
  const profit = formatBRL(kpis.profit.value)
  const from = period.from.split('-').reverse().join('/'), to = period.to.split('-').reverse().join('/')
  return <section>{alerts.data && alerts.data.length > 0 && <div className="alert-strip" role="status"><div className="alert-strip-head"><strong>{alerts.data.length} {alerts.data.length === 1 ? 'alerta aberto' : 'alertas abertos'}</strong><Link to="/alertas">Ver todos</Link></div><div className="alert-strip-items">{alerts.data.map((alert) => <Link className={alert.severity} key={alert.id} to={alertDestination(alert.type)}>{alert.severity === 'critical' ? <AlertOctagon /> : <AlertTriangle />}<span><strong>{alert.severity === 'critical' ? 'Crítico' : 'Atenção'}:</strong> {alert.title}</span></Link>)}</div></div>}<div className="page-heading"><div><h1>Visão geral</h1><p><span className="period-long">Resultado da operação de {from} a {to}.</span><span className="period-short">{from.slice(0, 5)} a {to}</span></p></div><span className="live-status"><i /> Atualiza a cada 30s</span></div><GlobalFilters /><DataWarnings warnings={allWarnings} /><div className="hero"><article className={`price-tag${isNegativeMoney(kpis.profit.value) ? ' loss' : ''}`}><span>Lucro do período</span><Price value={profit} /><footer>{kpis.profit.change_pct === null ? 'sem comparação' : `${kpis.profit.change_pct > 0 ? '+' : ''}${kpis.profit.change_pct.toLocaleString('pt-BR')}% vs. período anterior`}</footer></article><div className="kpi-grid hero-kpis">{moneyCards.map(([label, value, change, danger]) => <KpiCard key={label} label={label} value={value} change={change} danger={danger} />)}</div></div><div className="kpi-grid ratios">{ratioCards.map(([label, value, change, danger]) => <KpiCard key={label} label={label} value={value} change={change} danger={danger} />)}</div><section className="panel analytics-section"><h2>Comissão × investimento</h2><p>Veja quando o retorno acompanha — ou deixa de acompanhar — o valor investido.</p><MoneyChart commission={commission.data} spend={spend.data} /></section><LossTable filters={filters} onWarnings={setLossWarnings} /><section className="panel"><h2>Funil de conversão</h2><p>Da publicação até compradores identificados.</p><Funnel filters={filters} onWarnings={setFunnelWarnings} /></section></section>
}
