import type { components, operations } from './schema'

export type Alert = components['schemas']['AlertResponse']
export type AuditLog = components['schemas']['AuditLogResponse']
export type Campaign = components['schemas']['CampaignResponse']
export type CampaignCreate = components['schemas']['CampaignCreate']
export type CampaignMetrics = components['schemas']['CampaignMetrics']
export type Event = components['schemas']['EventResponse']
export type Expense = components['schemas']['ExpenseResponse']
export type ExpenseCreate = components['schemas']['ExpenseCreate']
export type ExpenseCategory = components['schemas']['ExpenseCategoryResponse']
export type Funnel = components['schemas']['FunnelResponse']
export type ImportResult = components['schemas']['ImportResult']
export type MetricBreakdownItem = components['schemas']['MetricBreakdownItem']
export type MetricBreakdownResponse = components['schemas']['MetricBreakdownResponse']
export type Sale = components['schemas']['SaleResponse']
export type SalesImportHistory = components['schemas']['SalesImportHistory']
export type TimeseriesResponse = components['schemas']['TimeseriesResponse']

export const metricDimensions = ['platform', 'account', 'bot', 'group', 'campaign', 'niche'] as const
export type MetricDimension = typeof metricDimensions[number]

type OverviewQuery = NonNullable<operations['overview_api_metrics_overview_get']['parameters']['query']>
export type MetricFilters = OverviewQuery & { from: string; to: string }

export const dimensionLabels: Record<MetricDimension, string> = {
  platform: 'Plataforma', account: 'Conta', bot: 'Bot', group: 'Grupo',
  campaign: 'Campanha', niche: 'Nicho',
}

export function granularityFor(from: string, to: string): 'day' | 'week' | 'month' {
  const days = Math.floor((Date.parse(`${to}T12:00:00Z`) - Date.parse(`${from}T12:00:00Z`)) / 86_400_000) + 1
  if (days <= 31) return 'day'
  if (days <= 186) return 'week'
  return 'month'
}
