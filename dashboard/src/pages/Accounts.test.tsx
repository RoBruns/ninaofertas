import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import type { User } from '../api/client'
import type { Account, Platform } from '../api/management'
import { AuthContext, type AuthContextValue } from '../auth/AuthContext'
import { ToastProvider } from '../components/Toast'
import { Accounts } from './Accounts'

const admin: User = { id: 'user-1', email: 'admin@nina.test', name: 'Admin', role: 'admin', is_active: true, last_login_at: null, created_at: '2026-09-23T10:00:00Z' }
const platform: Platform = { id: 1, slug: 'mercadolivre', name: 'Mercado Livre', is_active: true, capabilities: {} }
const account: Account = {
  id: 'account-1', platform: { id: 1, slug: 'mercadolivre', name: 'Mercado Livre' }, label: 'Conta ML', external_id: '123', status: 'active', config: {}, notes: null,
  credentials: [{ kind: 'cookie', status: 'expired', expires_at: null, last_rotated_at: null, last_used_at: null, last_success_at: null, last_error: 'HTTP 401', last_error_at: null, needs_renewal: true }],
  health: { status: 'error', message: 'Cookie expirado' }, created_at: '2026-09-23T10:00:00Z', updated_at: '2026-09-23T10:00:00Z',
}

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderAccounts(role: User['role'] = 'admin') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const auth: AuthContextValue = { user: { ...admin, role }, status: 'authenticated', login: vi.fn(), logout: vi.fn() }
  render(<QueryClientProvider client={queryClient}><ToastProvider><AuthContext.Provider value={auth}><MemoryRouter><Accounts /></MemoryRouter></AuthContext.Provider></ToastProvider></QueryClientProvider>)
  return queryClient
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('limpa a credencial, testa e não mantém o valor no DOM nem no cache', async () => {
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const url = new URL(request.url)
    requests.push(`${request.method} ${url.pathname}`)
    if (url.pathname === '/api/platforms') return json([platform])
    if (url.pathname.endsWith('/test')) return json({ ok: true, checked_at: '2026-09-23T10:01:00Z', message: 'válida' })
    if (request.method === 'PUT') return new Response(null, { status: 204 })
    return json({ items: [account], total: 1, page: 1, page_size: 100 })
  }))
  const queryClient = renderAccounts()
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Renovar credencial' }))
  const field = screen.getByLabelText('Cookie de sessão')
  await user.type(field, 'segredo-super-secreto')
  await user.click(screen.getByRole('button', { name: 'Salvar e testar' }))
  expect(field).toHaveValue('')
  expect(screen.queryByText('segredo-super-secreto')).not.toBeInTheDocument()
  expect(await screen.findByText('Funcionou')).toBeInTheDocument()
  expect(requests).toContain('POST /api/accounts/account-1/credentials/cookie/test')
  expect(JSON.stringify(queryClient.getQueryCache().getAll().map((query) => query.state.data))).not.toContain('segredo-super-secreto')
  expect(JSON.stringify(queryClient.getMutationCache().getAll().map((mutation) => mutation.state.variables))).not.toContain('segredo-super-secreto')
})

it('limpa a credencial também quando o envio falha', async () => {
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const url = new URL(request.url)
    if (url.pathname === '/api/platforms') return json([platform])
    if (request.method === 'PUT') return json({ error: { message: 'Falha ao salvar' } }, 500)
    return json({ items: [account], total: 1, page: 1, page_size: 100 })
  }))
  renderAccounts()
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Renovar credencial' }))
  const field = screen.getByLabelText('Cookie de sessão')
  await user.type(field, 'outro-segredo')
  await user.click(screen.getByRole('button', { name: 'Salvar e testar' }))
  expect(field).toHaveValue('')
  expect(screen.queryByText('outro-segredo')).not.toBeInTheDocument()
  expect(await screen.findByText('Falha ao salvar')).toBeInTheDocument()
})

it('lista os bots no conflito ao excluir uma conta', async () => {
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const url = new URL(request.url)
    if (url.pathname === '/api/platforms') return json([platform])
    if (request.method === 'DELETE') return json({ error: { message: 'Conta em uso', bots: [{ id: 'bot-1', name: 'Ofertas Casa' }, { id: 'bot-2', name: 'Ofertas Tech' }] } }, 409)
    return json({ items: [account], total: 1, page: 1, page_size: 100 })
  }))
  renderAccounts()
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Excluir' }))
  expect(await screen.findByText(/Bots vinculados: Ofertas Casa, Ofertas Tech/)).toBeInTheDocument()
})

it('não mostra ações de edição para viewer', async () => {
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => new URL(request.url).pathname === '/api/platforms' ? json([platform]) : json({ items: [account], total: 1, page: 1, page_size: 100 })))
  renderAccounts('viewer')
  await screen.findByText('Conta ML')
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument())
  expect(screen.queryByRole('button', { name: 'Renovar credencial' })).not.toBeInTheDocument()
})

const shopee: Platform = { id: 2, slug: 'shopee', name: 'Shopee', is_active: true, capabilities: {} }

it('nova conta Shopee exige App ID e o envia em config', async () => {
  const bodies: unknown[] = []
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const url = new URL(request.url)
    if (url.pathname === '/api/platforms') return json([shopee, platform])
    if (request.method === 'POST' && url.pathname === '/api/accounts') {
      bodies.push(await request.json())
      return json({ ...account, id: 'account-2', platform: shopee, credentials: [] }, 201)
    }
    return json({ items: [], total: 0, page: 1, page_size: 100 })
  }))
  renderAccounts()
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Nova conta' }))
  await user.type(screen.getByLabelText('Rótulo'), 'Shopee principal')
  expect(screen.getByLabelText('App ID')).toBeRequired()
  await user.type(screen.getByLabelText('App ID'), '18378021201')
  await user.click(screen.getByRole('button', { name: 'Salvar' }))
  await waitFor(() => expect(bodies).toHaveLength(1))
  expect(bodies[0]).toMatchObject({ platform_id: 2, label: 'Shopee principal', config: { app_id: '18378021201' } })
})

it('credencial da Shopee é cadastrada como app_secret', async () => {
  const requests: string[] = []
  const conta: Account = { ...account, id: 'account-2', platform: { id: 2, slug: 'shopee', name: 'Shopee' }, label: 'Shopee principal', config: { app_id: '1' }, credentials: [] }
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const url = new URL(request.url)
    requests.push(`${request.method} ${url.pathname}`)
    if (url.pathname === '/api/platforms') return json([shopee])
    if (url.pathname.endsWith('/test')) return json({ ok: true, checked_at: '2026-09-23T10:01:00Z', message: 'válida' })
    if (request.method === 'PUT') return new Response(null, { status: 204 })
    return json({ items: [conta], total: 1, page: 1, page_size: 100 })
  }))
  renderAccounts()
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Cadastrar credencial' }))
  await user.type(screen.getByLabelText('App Secret'), 'segredo')
  await user.click(screen.getByRole('button', { name: 'Salvar e testar' }))
  expect(await screen.findByText('Funcionou')).toBeInTheDocument()
  expect(requests).toContain('PUT /api/accounts/account-2/credentials/app_secret')
})
