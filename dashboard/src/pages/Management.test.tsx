import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import type { User } from '../api/client'
import type { Bot, Group, Phone } from '../api/management'
import { AuthContext, type AuthContextValue } from '../auth/AuthContext'
import { ToastProvider } from '../components/Toast'
import { BotDetail } from './BotDetail'
import { Bots } from './Bots'
import { PhonesGroups } from './PhonesGroups'

const admin: User = { id: 'user-1', email: 'admin@nina.test', name: 'Admin', role: 'admin', is_active: true, last_login_at: null, created_at: '2026-09-23T10:00:00Z' }
const bot: Bot = {
  id: 'bot-1', name: 'Bot Casa', slug: 'bot-casa', niche_id: null, phone_id: 'phone-1', status: 'paused', group_ids: ['group-1'], account_ids: [], message_template: null,
  settings: { schema_version: 1, filters: { preco_minimo: 20, preco_maximo: 5000, desconto_minimo: 15, max_vendas: 20, max_idade_oferta_horas: 0 }, pacing: { max_ofertas_por_ciclo: 1, intervalo_minutos_entre_ofertas: 5, max_ofertas_por_rajada: 3, janela_rajada_minutos: 15, pausa_entre_rajadas_minutos: 35, max_ofertas_por_hora: 6, max_ofertas_por_dia: 80, max_ofertas_globais_por_hora: 8, max_ofertas_globais_por_dia: 90 }, content: { aceitar_cupons: true, aceitar_campanhas: false, max_cupons_por_dia: 2, baseline_ciclos: 5 }, schedule: { check_interval: 60, quiet_hours: { start: '23:00', end: '07:00' } } },
  last_run_at: null, last_success_at: null, created_at: '2026-09-23T10:00:00Z', updated_at: '2026-09-23T10:00:00Z',
}
const phone: Phone = { id: 'phone-1', label: 'Principal', number: '5511999999999', evolution_instance: 'nina', status: 'connected', last_seen_at: null, created_at: '2026-09-23T10:00:00Z' }
const group: Group = { id: 'group-1', phone_id: 'phone-1', whatsapp_id: '123@g.us', name: 'Promoções', participants: 100, is_announce: true, bot_is_admin: false, status: 'active', discovered_at: null, last_synced_at: null, warning: 'Grupo somente-admins e o bot não é admin: mensagens não serão entregues' }

function json(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } }) }

function Providers({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const auth: AuthContextValue = { user: admin, status: 'authenticated', login: vi.fn(), logout: vi.fn() }
  return <QueryClientProvider client={queryClient}><ToastProvider><AuthContext.Provider value={auth}>{children}</AuthContext.Provider></ToastProvider></QueryClientProvider>
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('mostra o aviso de grupo somente-admins', async () => {
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (path === '/api/phones') return json({ items: [phone], total: 1, page: 1, page_size: 100 })
    if (path === '/api/groups') return json({ items: [group], total: 1, page: 1, page_size: 200 })
    return json({ items: [bot], total: 1, page: 1, page_size: 200 })
  }))
  render(<Providers><MemoryRouter><PhonesGroups /></MemoryRouter></Providers>)
  expect(await screen.findByText(/mensagens não serão entregues/)).toBeInTheDocument()
})

function Destination() { return <span>{useLocation().pathname}</span> }

it('navega para a cópia ao duplicar bot', async () => {
  const copy = { ...bot, id: 'bot-copy', name: 'Bot Casa (cópia)', status: 'paused' as const }
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (request.method === 'POST' && path.endsWith('/duplicate')) return json(copy, 201)
    if (path.endsWith('/health')) return json({ status: 'ok', message: 'Funcionando', last_run_status: null, last_run_at: null, credential_issues: [], group_issues: [] })
    if (path === '/api/niches') return json([])
    if (path === '/api/phones') return json({ items: [phone], total: 1, page: 1, page_size: 100 })
    return json({ items: [bot], total: 1, page: 1, page_size: 100 })
  }))
  render(<Providers><MemoryRouter initialEntries={['/bots']}><Routes><Route path="/bots" element={<Bots />} /><Route path="/bots/:id" element={<Destination />} /></Routes></MemoryRouter></Providers>)
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Duplicar' }))
  expect(await screen.findByText('/bots/bot-copy')).toBeInTheDocument()
})

it('mantém o erro 422 de risco de ban junto ao campo de ritmo', async () => {
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (request.method === 'PATCH') return json({ error: { message: 'Este ritmo aumenta o risco de banimento do número', fields: { 'settings.pacing.max_ofertas_por_hora': 'acima do limite seguro' } } }, 422)
    if (path === '/api/bots/bot-1') return json(bot)
    if (path === '/api/niches') return json([])
    if (path === '/api/phones') return json({ items: [phone], total: 1, page: 1, page_size: 100 })
    if (path === '/api/groups') return json({ items: [group], total: 1, page: 1, page_size: 200 })
    if (path === '/api/accounts') return json({ items: [], total: 0, page: 1, page_size: 200 })
    if (path.endsWith('/runs')) return json({ items: [], total: 0, page: 1, page_size: 25 })
    return json({ status: 'ok', message: 'Funcionando', last_run_status: null, last_run_at: null, credential_issues: [], group_issues: [] })
  }))
  render(<Providers><MemoryRouter initialEntries={['/bots/bot-1']}><Routes><Route path="/bots/:id" element={<BotDetail />} /></Routes></MemoryRouter></Providers>)
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Salvar alterações' }))
  const warning = await screen.findByRole('alert')
  expect(warning).toHaveTextContent('Risco para o número')
  expect(warning).toHaveTextContent('risco de banimento')
  expect(screen.getByText('acima do limite seguro')).toBeInTheDocument()
})
