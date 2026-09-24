import { useQuery } from '@tanstack/react-query'
import { api, ApiError, getApiError } from '../api/client'
import { KpiCard } from '../components/KpiCard'
import { Spinner } from '../components/Spinner'
import { formatBRL, formatCount, formatPercent, formatRatio, isNegativeMoney } from '../lib/format'

function localDate(offsetDays = 0) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Sao_Paulo', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(Date.now() + offsetDays * 86_400_000))
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

async function loadOverview() {
  const { data, error, response } = await api.GET('/api/metrics/overview', { params: { query: { from: localDate(-29), to: localDate() } } })
  if (!data) {
    throw new ApiError(getApiError(error), response.status)
  }
  return data
}

export function Overview() {
  const query = useQuery({ queryKey: ['metrics', 'overview'], queryFn: loadOverview, refetchInterval: 30_000 })
  if (query.isPending) return <Spinner label="Carregando indicadores" />
  if (query.isError) return <section className="page-error" role="alert"><h2>Não foi possível carregar a visão geral</h2><p>{query.error.message}</p><button className="button primary" onClick={() => void query.refetch()}>Tentar novamente</button></section>

  const { kpis, warnings, period } = query.data
  const cards = [
    ['Faturamento', formatBRL(kpis.revenue.value), kpis.revenue.change_pct, false],
    ['Comissão', formatBRL(kpis.commission.value), kpis.commission.change_pct, false],
    ['Comissão pendente', formatBRL(kpis.commission_pending.value), kpis.commission_pending.change_pct, false],
    ['Investimento', formatBRL(kpis.spend.value), kpis.spend.change_pct, false],
    ['Lucro', formatBRL(kpis.profit.value), kpis.profit.change_pct, isNegativeMoney(kpis.profit.value)],
    ['ROI', formatPercent(kpis.roi.value), kpis.roi.change_pct, false],
    ['ROAS', formatRatio(kpis.roas.value), kpis.roas.change_pct, false],
    ['Custo por venda', formatBRL(kpis.cost_per_sale.value), kpis.cost_per_sale.change_pct, false],
    ['Pedidos', formatCount(kpis.orders.value), kpis.orders.change_pct, false],
    ['Envios', formatCount(kpis.sends.value), kpis.sends.change_pct, false],
  ] as const

  return <section><div className="page-heading"><div><p className="eyebrow">ÚLTIMOS 30 DIAS</p><h1>Visão geral</h1><p>De {period.from.split('-').reverse().join('/')} a {period.to.split('-').reverse().join('/')}</p></div><span className="live-status"><i /> Atualiza a cada 30s</span></div>{warnings.length > 0 && <div className="warnings" role="status"><strong>Atenção aos dados</strong>{warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}<div className="kpi-grid">{cards.map(([label, value, change, danger]) => <KpiCard key={label} label={label} value={value} change={change} danger={danger} />)}</div></section>
}
