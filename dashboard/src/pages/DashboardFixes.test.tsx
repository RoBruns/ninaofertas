import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { ToastProvider } from '../components/Toast'
import { AuthContext } from '../auth/AuthContext'
import { Sales } from './Sales'
import { Logs } from './Logs'
import { Audit } from './Audit'
import { Alerts } from './Alerts'

function json(value: unknown) { return new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } }) }
function show(children: React.ReactNode) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ToastProvider><MemoryRouter>{children}</MemoryRouter></ToastProvider></QueryClientProvider>)
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('mostra data e hora de Brasília nos logs', async () => {
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => json(new URL(request.url).pathname === '/api/events'
    ? { items: [{ id: 1, type: 'diagnóstico', level: 'info', message: 'Ciclo concluído', created_at: '2026-10-14T02:45:00Z' }], total: 1, page: 1, page_size: 25 }
    : { items: [] })))
  show(<Logs />)
  expect(await screen.findByText('13/10/2026 23:45')).toBeInTheDocument()
})

it('separa a plataforma do CSV e volta à página 1 ao mudar qualquer filtro de vendas', async () => {
  const urls: URL[] = []
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const url = new URL(request.url); urls.push(url)
    if (url.pathname === '/api/platforms') return json([{ id: 1, name: 'Shopee' }, { id: 2, name: 'Mercado Livre' }])
    if (url.pathname === '/api/sales/imports') return json([])
    return json({ items: url.pathname === '/api/bots' ? [{ id: 'bot1', name: 'Bot Casa' }] : [], total: 100, page: Number(url.searchParams.get('page') || 1), page_size: 25 })
  }))
  show(<Sales />)
  const user = userEvent.setup()
  const csv = await screen.findByLabelText('Plataforma do CSV')
  await user.selectOptions(await screen.findByLabelText('Plataforma'), '1')
  await user.selectOptions(csv, '2')
  expect(screen.getByLabelText('Plataforma')).toHaveValue('1')
  expect(csv).toHaveValue('2')
  expect(screen.getByText('Nenhuma importação registrada.')).toBeInTheDocument()
  const changes: Array<[string, string]> = [['Status', 'pending'], ['Plataforma', '2'], ['Bot', 'bot1'], ['De', '2026-10-12'], ['Até', '2026-10-13']]
  for (const [label, value] of changes) {
    await user.click(screen.getByRole('button', { name: 'Próxima' }))
    expect(screen.getByText('Página 2')).toBeInTheDocument()
    const input = screen.getByLabelText(label)
    if (input.tagName === 'SELECT') await user.selectOptions(input, value)
    else {
      fireEvent.change(input, { target: { value } })
    }
    await waitFor(() => expect(screen.getByText('Página 1')).toBeInTheDocument())
    await waitFor(() => expect(urls.filter(url => url.pathname === '/api/sales').at(-1)?.searchParams.get('page')).toBe('1'))
  }
})

it('datas da auditoria voltam à página 1', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json({ items: [], total: 100, page_size: 25 })))
  show(<Audit />)
  const user = userEvent.setup()
  for (const label of ['De', 'Até']) {
    await waitFor(() => expect(screen.getByRole('button', { name: 'Próxima' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: 'Próxima' }))
    expect(screen.getByText('Página 2')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(label), { target: { value: '2026-10-13' } })
    expect(screen.getByText('Página 1')).toBeInTheDocument()
  }
})

it('resolver causa de sincronização e conciliação aponta para vendas', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json({ items: ['sales_sync_stale', 'ml_reconciliation_mismatch'].map((type, id) => ({ id, type, severity: 'warning', status: 'open', title: type, first_seen_at: '2026-10-13T12:00:00Z', last_seen_at: '2026-10-13T12:00:00Z' })) })))
  show(<AuthContext.Provider value={{ user: null, status: 'authenticated', login: vi.fn(), logout: vi.fn() }}><Alerts /></AuthContext.Provider>)
  const links = await screen.findAllByRole('link', { name: 'Resolver causa' })
  expect(links).toHaveLength(2)
  links.forEach(link => expect(link).toHaveAttribute('href', '/vendas'))
})
