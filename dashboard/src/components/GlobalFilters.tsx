import { useQuery } from '@tanstack/react-query'
import { api, apiFailure } from '../api/client'
import { presetDates, type Preset } from '../lib/metricFilters'
import { useMetricFilters } from './useMetricFilters'

const filterKeys = ['platform_id', 'account_id', 'bot_id', 'niche_id', 'group_id', 'campaign_id', 'phone_id'] as const

function useOptions() {
  return useQuery({ queryKey: ['global-filter-options'], queryFn: async () => {
    const [platforms, accounts, bots, niches, groups, campaigns, phones] = await Promise.all([
      api.GET('/api/platforms'),
      api.GET('/api/accounts', { params: { query: { page: 1, page_size: 200 } } }),
      api.GET('/api/bots', { params: { query: { page: 1, page_size: 200 } } }),
      api.GET('/api/niches'),
      api.GET('/api/groups', { params: { query: { page: 1, page_size: 200 } } }),
      api.GET('/api/campaigns', { params: { query: { page: 1, page_size: 200 } } }),
      api.GET('/api/phones', { params: { query: { page: 1, page_size: 200 } } }),
    ])
    for (const result of [platforms, accounts, bots, niches, groups, campaigns, phones]) {
      if (!result.data) throw apiFailure(result.error, result.response)
    }
    return {
      platforms: platforms.data!, accounts: accounts.data!.items, bots: bots.data!.items,
      niches: niches.data!, groups: groups.data!.items, campaigns: campaigns.data!.items,
      phones: phones.data!.items,
    }
  }, staleTime: 60_000 })
}

export function GlobalFilters() {
  const { filters, params, update } = useMetricFilters()
  const options = useOptions()
  const preset = (params.get('preset') || '30d') as Preset
  const setPreset = (value: Preset) => {
    if (value === 'custom') return update({ preset: value })
    const dates = presetDates(value)
    update({ preset: value, from: dates.from, to: dates.to })
  }
  const select = (label: string, key: typeof filterKeys[number], items: ReadonlyArray<{ id: string | number; name?: string | null; label?: string }>) => <label className="filter-field"><span>{label}</span><select aria-label={label} value={params.get(key) || ''} onChange={(event) => update({ [key]: event.target.value || undefined })}><option value="">Todos</option>{items.map((item) => <option key={item.id} value={item.id}>{item.name || item.label || item.id}</option>)}</select></label>
  return <section className="global-filters" aria-label="Filtros globais">
    <div className="filter-presets" role="group" aria-label="Período">{([['today', 'Hoje'], ['7d', '7 dias'], ['30d', '30 dias'], ['month', 'Este mês'], ['previous_month', 'Mês anterior'], ['custom', 'Personalizado']] as const).map(([value, label]) => <button type="button" className={preset === value ? 'active' : ''} key={value} onClick={() => setPreset(value)}>{label}</button>)}</div>
    {preset === 'custom' && <div className="custom-dates"><label className="filter-field"><span>De</span><input aria-label="De" type="date" value={filters.from} onChange={(event) => update({ from: event.target.value })} /></label><label className="filter-field"><span>Até</span><input aria-label="Até" type="date" value={filters.to} onChange={(event) => update({ to: event.target.value })} /></label></div>}
    {options.data && <div className="filter-selects">
      {select('Plataforma', 'platform_id', options.data.platforms)}
      {select('Conta', 'account_id', options.data.accounts)}
      {select('Bot', 'bot_id', options.data.bots)}
      {select('Nicho', 'niche_id', options.data.niches)}
      {select('Grupo', 'group_id', options.data.groups)}
      {select('Campanha', 'campaign_id', options.data.campaigns)}
      {select('Telefone', 'phone_id', options.data.phones)}
    </div>}
    {filterKeys.some((key) => params.has(key)) && <button className="clear-filters" type="button" onClick={() => update(Object.fromEntries(filterKeys.map((key) => [key, undefined])))}>Limpar filtros</button>}
  </section>
}
