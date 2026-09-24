import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { Audit } from './Audit'

function json(value: unknown) {
  return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function renderAudit() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={queryClient}><Audit /></QueryClientProvider>)
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('mostra o e-mail e nome do autor e identifica ações do sistema', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json({
    items: [
      {
        id: 1,
        user_id: '11111111-1111-1111-1111-111111111111',
        user_email: 'autora@nina.test',
        user_name: 'Nina Silva',
        entity_type: 'campaign',
        entity_id: 'campaign-1',
        action: 'update',
        before: { name: 'Antes' },
        after: { name: 'Depois' },
        ip: null,
        created_at: '2026-09-24T12:00:00Z',
      },
      {
        id: 2,
        user_id: null,
        user_email: null,
        user_name: null,
        entity_type: 'sale',
        entity_id: 'sale-1',
        action: 'sync',
        before: null,
        after: null,
        ip: null,
        created_at: '2026-09-24T13:00:00Z',
      },
    ],
    total: 2,
    page: 1,
    page_size: 25,
  })))

  renderAudit()

  expect(await screen.findByText('Nina Silva (autora@nina.test)')).toBeInTheDocument()
  expect(screen.getByText('Sistema')).toBeInTheDocument()
  expect(screen.queryByText(/11111111-1111-1111-1111-111111111111/)).not.toBeInTheDocument()
})
