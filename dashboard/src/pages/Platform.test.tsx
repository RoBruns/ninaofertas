import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { User } from '../api/client'
import { AuthContext, type AuthContextValue } from '../auth/AuthContext'
import { ToastProvider } from '../components/Toast'
import { Sidebar } from '../components/Sidebar'
import { Platform } from './Platform'
import { PhonesGroups } from './PhonesGroups'

const admin: User = { id: 'user-b', tenant: { id: 'tenant-b', name: 'Operação cliente', is_internal: false }, is_platform_admin: false, email: 'cliente@teste.com', name: 'Cliente', role: 'admin', is_active: true, last_login_at: null, created_at: '2026-10-14T10:00:00Z' }
function json(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } }) }
function renderPage(children: ReactNode, platformAdmin = false) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const auth: AuthContextValue = { user: { ...admin, is_platform_admin: platformAdmin }, status: 'authenticated', login: vi.fn(), logout: vi.fn() }
  render(<QueryClientProvider client={queryClient}><ToastProvider><AuthContext.Provider value={auth}><MemoryRouter>{children}</MemoryRouter></AuthContext.Provider></ToastProvider></QueryClientProvider>)
}
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('mostra a conta no menu e recusa o painel para admin comum', async () => {
  const paths: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => { paths.push(new URL(request.url).pathname); return json({ total: 0 }) }))
  renderPage(<><Sidebar open onClose={() => {}} /><Platform /></>)
  expect(screen.getByText('Operação cliente')).toBeInTheDocument()
  expect(screen.getByText('Acesso restrito')).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Plataforma' })).not.toBeInTheDocument()
  expect(paths).not.toContain('/api/platform/tenants')
})

it('só suspende depois de confirmar na UI e permite reativar', async () => {
  let status = 'active'
  const writes: unknown[] = []
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    if (request.method === 'PATCH') { const body = await request.json() as { status: string }; writes.push(body); status = body.status; return json({ id: 'cliente-a', status }) }
    return json([{ id: 'cliente-a', name: 'Conta A', status, is_internal: false, created_at: '2026-10-14T10:00:00Z', users_count: 1, active_bots_count: 2, successful_sends_30d: 42 }])
  }))
  renderPage(<Platform />, true)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Suspender' }))
  expect(writes).toHaveLength(0)
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancelar' }))
  expect(writes).toHaveLength(0)
  await user.click(screen.getByRole('button', { name: 'Suspender' }))
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Suspender' }))
  await user.click(await screen.findByRole('button', { name: 'Reativar' }))
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Reativar' }))
  expect(writes).toEqual([{ status: 'suspended' }, { status: 'active' }])
})

it('cliente cadastra telefone sem campo de instância e conecta pela rota nova', async () => {
  let phone: { id: string; label: string; number: string; status: string; evolution_instance: null } | null = null
  const requests: string[] = []
  let saved: unknown
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname; requests.push(`${request.method} ${path}`)
    if (path.endsWith('/instance')) return json({ qrcode_base64: 'UVJfVEVTVEU=', expires_at: '2026-10-14T12:00:00Z' })
    if (path === '/api/phones' && request.method === 'POST') {
      saved = await request.json(); phone = { id: 'phone-b', label: 'Cliente', number: '5511999990000', status: 'unknown', evolution_instance: null }; return json(phone, 201)
    }
    return json({ items: path === '/api/phones' && phone ? [phone] : [], total: 0 })
  }))
  renderPage(<PhonesGroups />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Novo telefone' }))
  expect(screen.queryByLabelText('Instância Evolution')).not.toBeInTheDocument()
  await user.type(screen.getByLabelText('Rótulo'), 'Cliente')
  await user.type(screen.getByLabelText('Número (opcional)'), '5511999990000')
  await user.click(screen.getByRole('button', { name: 'Salvar' }))
  await user.click(await screen.findByRole('button', { name: 'Conectar WhatsApp' }))
  expect(await screen.findByAltText('QR code de Cliente')).toBeInTheDocument()
  expect(saved).toEqual({ label: 'Cliente', number: '5511999990000' })
  expect(requests).toContain('POST /api/phones/phone-b/instance')
})
