import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { GlobalFilters } from '../components/GlobalFilters'
import { Overview } from './Overview'

function json(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } }) }
function Location() { const location = useLocation(); return <output data-testid="location">{`${location.pathname}${location.search}`}</output> }
function Providers({ children, initial = '/' }: { children: React.ReactNode; initial?: string }) { return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[initial]}>{children}</MemoryRouter></QueryClientProvider> }

const money = { value: '10.00', previous: '5.00', change_pct: 100 }
const count = { value: 2, previous: 1, change_pct: 100 }
const ratio = { value: 1, previous: .5, change_pct: 100 }
const overview = { period: { from: '2026-09-01', to: '2026-09-30' }, kpis: { revenue: money, commission: money, commission_pending: money, spend: money, traffic_spend: money, profit: money, cost_per_sale: money, cost_per_buyer: money, cost_per_join: money, orders: count, buyers: count, group_joins: count, sends: count, clicks: count, roi: ratio, roas: ratio, conversion: ratio }, warnings: [] }

function mockAnalytics() {
  const urls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const url = new URL(request.url); urls.push(url.toString())
    if (url.pathname === '/api/metrics/overview') return json(overview)
    if (url.pathname === '/api/metrics/timeseries') return json({ period: overview.period, metric: url.searchParams.get('metric'), granularity: 'day', points: [], warnings: [] })
    if (url.pathname === '/api/metrics/funnel') return json({ period: overview.period, sends: 10, clicks: null, orders: 2, buyers: null, conversion: null, warnings: ['Sem cliques'] })
    if (url.pathname === '/api/metrics/by-bot') return json({ period: overview.period, warnings: [], items: [{ id: 'good', name: 'Bom', revenue: '20.00', commission: '20.00', commission_pending: '0.00', orders: 1, buyers: 1, spend: '5.00', traffic_spend: '5.00', profit: '15.00', roi: 3, roas: 4, cost_per_sale: '5.00', cost_per_buyer: '5.00', cost_per_join: null, group_joins: 0, sends: 1, clicks: 1, conversion: 1 }, { id: 'bad', name: 'Ruim', revenue: '1.00', commission: '1.00', commission_pending: '0.00', orders: 1, buyers: 1, spend: '5.00', traffic_spend: '5.00', profit: '-4.00', roi: -.8, roas: .2, cost_per_sale: '5.00', cost_per_buyer: '5.00', cost_per_join: null, group_joins: 0, sends: 1, clicks: 1, conversion: 1 }] })
    if (url.pathname === '/api/alerts') return json({ items: [{ id: 'a1', owner_id: 'u', type: 'auth_expired', severity: 'critical', entity_type: 'account', entity_id: 'x', title: 'Renove a credencial', detail: null, status: 'open', first_seen_at: '2026-09-01T00:00:00Z', last_seen_at: '2026-09-02T00:00:00Z', resolved_at: null, dedup_key: 'x' }], total: 1, page: 1, page_size: 5 })
    if (url.pathname === '/api/bots') return json({ items: [{ id: 'b1', name: 'Bot 1' }], total: 1, page: 1, page_size: 200 })
    if (url.pathname === '/api/platforms' || url.pathname === '/api/niches') return json([])
    return json({ items: [], total: 0, page: 1, page_size: 200 })
  }))
  return urls
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('restaura filtros da URL e grava mudanças nela', async () => {
  mockAnalytics()
  render(<Providers initial="/?from=2026-09-01&to=2026-09-30&bot_id=b1"><GlobalFilters /><Location /></Providers>)
  expect(await screen.findByLabelText('Bot')).toHaveValue('b1')
  await userEvent.setup().click(screen.getByRole('button', { name: '7 dias' }))
  expect(screen.getByTestId('location')).toHaveTextContent('bot_id=b1')
  expect(screen.getByTestId('location')).toHaveTextContent('preset=7d')
})

it('envia filtros ativos à overview, ordena perdas, aplica linha e preserva null no funil', async () => {
  const urls = mockAnalytics()
  render(<Providers initial="/?from=2026-09-01&to=2026-09-30&platform_id=3"><Overview /><Location /></Providers>)
  expect(await screen.findByText('Onde estou perdendo dinheiro')).toBeInTheDocument()
  await waitFor(() => expect(urls.find((url) => url.includes('/api/metrics/overview'))).toContain('platform_id=3'))
  const table = screen.getByRole('table')
  const rows = within(table).getAllByRole('row')
  expect(rows[1]).toHaveTextContent('Ruim')
  expect(within(rows[1]).getByText('-R$ 4,00')).toHaveClass('negative-money')
  expect((await screen.findAllByText('sem dados')).length).toBeGreaterThanOrEqual(2)
  expect(screen.getByRole('link', { name: /Renove a credencial/ })).toHaveAttribute('href', '/contas')
  await userEvent.setup().click(rows[1])
  expect(screen.getByTestId('location')).toHaveTextContent('bot_id=bad')
})
