import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { dimensionLabels, type MetricBreakdownItem, type MetricDimension } from '../api/analytics'
import { api, apiFailure } from '../api/client'
import { GlobalFilters } from '../components/GlobalFilters'
import { useMetricFilters } from '../components/useMetricFilters'
import { Spinner } from '../components/Spinner'
import { formatBRL, formatCount, formatPercent, formatRatio, isNegativeMoney } from '../lib/format'
import { compareDecimalStrings } from '../lib/moneyInput'

type SortKey = keyof Pick<MetricBreakdownItem, 'name' | 'revenue' | 'commission' | 'spend' | 'profit' | 'roi' | 'roas' | 'cost_per_sale' | 'cost_per_join' | 'group_joins' | 'orders' | 'sends' | 'clicks' | 'conversion'>

export function Performance() {
  const { filters } = useMetricFilters()
  const [dimension, setDimension] = useState<MetricDimension>('account')
  const [sort, setSort] = useState<SortKey>('profit')
  const [descending, setDescending] = useState(true)
  const query = useQuery({ queryKey: ['performance', dimension, filters], queryFn: async () => {
    const params = { query: { ...filters } }
    const result = dimension === 'platform' ? await api.GET('/api/metrics/by-platform', { params }) : dimension === 'account' ? await api.GET('/api/metrics/by-account', { params }) : dimension === 'bot' ? await api.GET('/api/metrics/by-bot', { params }) : dimension === 'group' ? await api.GET('/api/metrics/by-group', { params }) : dimension === 'campaign' ? await api.GET('/api/metrics/by-campaign', { params }) : await api.GET('/api/metrics/by-niche', { params })
    if (!result.data) throw apiFailure(result.error, result.response)
    return result.data
  }, refetchInterval: 30_000 })
  const botHealth = useQuery({ queryKey: ['performance-bot-health', query.data?.items.map((item) => item.id)], enabled: dimension === 'bot' && Boolean(query.data), queryFn: async () => Object.fromEntries(await Promise.all((query.data?.items || []).flatMap((item) => typeof item.id === 'string' ? [api.GET('/api/bots/{bot_id}/health', { params: { path: { bot_id: item.id } } }).then((result) => { if (!result.data) throw apiFailure(result.error, result.response); return [item.id, result.data] as const })] : []))) , refetchInterval: 30_000 })
  const chooseSort = (key: SortKey) => { if (sort === key) setDescending((value) => !value); else { setSort(key); setDescending(true) } }
  const items = [...(query.data?.items || [])].sort((a, b) => {
    const av = a[sort], bv = b[sort]
    if (av === null) return 1
    if (bv === null) return -1
    const moneyKeys: ReadonlySet<SortKey> = new Set(['revenue', 'commission', 'spend', 'profit', 'cost_per_sale'])
    const result = sort === 'name' ? String(av).localeCompare(String(bv)) : moneyKeys.has(sort) ? compareDecimalStrings(String(av), String(bv)) : Number(av) - Number(bv)
    return descending ? -result : result
  })
  const columns: Array<[SortKey, string, (item: MetricBreakdownItem) => string]> = [
    ['revenue', 'Receita', (item) => formatBRL(item.revenue)], ['commission', 'Comissão', (item) => formatBRL(item.commission)], ['spend', 'Investimento', (item) => formatBRL(item.spend)], ['profit', 'Lucro', (item) => formatBRL(item.profit)], ['roi', 'ROI', (item) => formatPercent(item.roi)], ['roas', 'ROAS', (item) => formatRatio(item.roas)], ['cost_per_sale', 'Custo/venda', (item) => formatBRL(item.cost_per_sale)], ['cost_per_join', 'Custo/entrada', (item) => formatBRL(item.cost_per_join)], ['group_joins', 'Entradas', (item) => formatCount(item.group_joins)], ['orders', 'Pedidos', (item) => formatCount(item.orders)], ['sends', 'Envios', (item) => formatCount(item.sends)], ['clicks', 'Cliques', (item) => formatCount(item.clicks)], ['conversion', 'Conversão', (item) => formatPercent(item.conversion)],
  ]
  return <section><div className="page-heading"><div><p className="eyebrow">COMPARATIVO</p><h1>Desempenho</h1><p>Descubra o que performa e onde o investimento não volta.</p></div><label className="filter-field"><span>Dimensão</span><select value={dimension} onChange={(event) => setDimension(event.target.value as MetricDimension)}>{Object.entries(dimensionLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label></div><GlobalFilters />{query.isPending ? <Spinner label="Carregando comparativo" /> : <><div className="warnings">{query.data?.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div><div className="responsive-table performance-table"><table><thead><tr><th><button onClick={() => chooseSort('name')}>{dimensionLabels[dimension]}</button></th>{dimension === 'bot' && <th>Saúde</th>}{columns.map(([key, label]) => <th key={key}><button onClick={() => chooseSort(key)}>{label}{sort === key ? descending ? ' ↓' : ' ↑' : ''}</button></th>)}</tr></thead><tbody>{items.map((item) => <tr key={item.id}><td data-label={dimensionLabels[dimension]}>{item.name}</td>{dimension === 'bot' && <td data-label="Saúde">{typeof item.id === 'string' ? botHealth.data?.[item.id]?.message || 'sem dados' : 'sem dados'}</td>}{columns.map(([key, label, render]) => <td key={key} data-label={label} className={key === 'profit' && isNegativeMoney(item.profit) ? 'negative-money' : ''}>{render(item)}</td>)}</tr>)}</tbody></table></div></>}</section>
}
