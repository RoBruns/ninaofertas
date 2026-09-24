import { useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { MetricFilters } from '../api/analytics'
import { presetDates } from '../lib/metricFilters'

export function useMetricFilters() {
  const [params, setParams] = useSearchParams()
  const defaults = presetDates('30d')
  useEffect(() => {
    if (params.has('from') && params.has('to')) return
    const next = new URLSearchParams(params)
    if (!next.has('from')) next.set('from', defaults.from)
    if (!next.has('to')) next.set('to', defaults.to)
    if (!next.has('preset')) next.set('preset', '30d')
    setParams(next, { replace: true })
  }, [defaults.from, defaults.to, params, setParams])
  const filters = useMemo<MetricFilters>(() => ({
    from: params.get('from') || defaults.from,
    to: params.get('to') || defaults.to,
    ...(params.get('platform_id') ? { platform_id: Number(params.get('platform_id')) } : {}),
    ...(params.get('account_id') ? { account_id: params.get('account_id')! } : {}),
    ...(params.get('bot_id') ? { bot_id: params.get('bot_id')! } : {}),
    ...(params.get('niche_id') ? { niche_id: Number(params.get('niche_id')) } : {}),
    ...(params.get('group_id') ? { group_id: params.get('group_id')! } : {}),
    ...(params.get('campaign_id') ? { campaign_id: params.get('campaign_id')! } : {}),
    ...(params.get('phone_id') ? { phone_id: params.get('phone_id')! } : {}),
  }), [params, defaults.from, defaults.to])
  const update = (values: Partial<Record<keyof MetricFilters | 'preset', string | undefined>>) => {
    const next = new URLSearchParams(params)
    Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key))
    setParams(next)
  }
  return { filters, params, update }
}
