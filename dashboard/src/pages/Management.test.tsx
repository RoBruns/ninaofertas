import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
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

const admin: User = { tenant: { id: 'tenant-1', name: 'Opera\u00e7\u00e3o Nina', is_internal: true }, is_platform_admin: true, id: 'user-1', email: 'admin@nina.test', name: 'Admin', role: 'admin', is_active: true, last_login_at: null, created_at: '2026-09-23T10:00:00Z' }
const bot: Bot = { is_test: false, archived_at: null, test_source_bot_id: null,
  id: 'bot-1', name: 'Bot Casa', slug: 'bot-casa', niche_id: null, phone_id: 'phone-1', status: 'paused', group_ids: ['group-1'], account_ids: [], message_template: null,
  settings: { schema_version: 1, filters: { preco_minimo: 20, preco_maximo: 5000, desconto_minimo: 15, max_vendas: 20, origem_produtos: 'novidades', min_vendas: 100, comissao_minima_reais: 0, prioridade_loja: 'alternar', publico_alvo: '', classificador_publico: 'jev', relevancia_minima: 0.6, max_idade_oferta_horas: 0, uma_loja_por_ciclo: false, ml_ignora_desconto_e_vendas: false, ml_categoria_dispensa_nicho: false }, pacing: { max_ofertas_por_ciclo: 1, intervalo_minutos_entre_ofertas: 5, max_ofertas_por_rajada: 3, janela_rajada_minutos: 15, pausa_entre_rajadas_minutos: 35, max_ofertas_por_hora: 6, max_ofertas_por_dia: 80, max_ofertas_globais_por_hora: 8, max_ofertas_globais_por_dia: 90 }, content: { recado_instagram: false, aceitar_cupons: true, aceitar_campanhas: false, cupom_venda_indireta: false, max_cupons_por_dia: 2, baseline_ciclos: 5 }, schedule: { check_interval: 60, quiet_hours: { start: '23:00', end: '07:00' } } },
  last_run_at: null, last_success_at: null, created_at: '2026-09-23T10:00:00Z', updated_at: '2026-09-23T10:00:00Z',
}
const phone: Phone = { has_instance_token: false, instance_token_fingerprint: null, id: 'phone-1', label: 'Principal', number: '5511999999999', evolution_instance: 'nina', status: 'connected', last_seen_at: null, created_at: '2026-09-23T10:00:00Z' }
const group: Group = { id: 'group-1', phone_id: 'phone-1', whatsapp_id: '123@g.us', name: 'Promoções', participants: 100, is_announce: true, bot_is_admin: false, status: 'active', discovered_at: null, last_synced_at: null, warning: 'Grupo somente-admins e o bot não é admin: mensagens não serão entregues' }

function json(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } }) }

function Providers({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const auth: AuthContextValue = { user: admin, status: 'authenticated', login: vi.fn(), logout: vi.fn() }
  return <QueryClientProvider client={queryClient}><ToastProvider><AuthContext.Provider value={auth}>{children}</AuthContext.Provider></ToastProvider></QueryClientProvider>
}

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it.each([10000, 60000])('renova QR automaticamente e fecha ao conectar (validade %i ms)', async (validity) => {
  vi.useFakeTimers()
  let connected = false, statusCalls = 0, qrCalls = 0
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (path === '/api/phones') return json({ items: [{ ...phone, status: connected ? 'connected' : 'connecting' }] })
    if (path.endsWith('/instance')) return json({ qrcode_base64: 'PRIMEIRO', expires_at: new Date(Date.now() + validity).toISOString() })
    if (path.endsWith('/status')) { statusCalls++; return json({ ...phone, status: connected ? 'connected' : 'connecting' }) }
    if (path.endsWith('/qrcode')) { qrCalls++; return json({ qrcode_base64: 'NOVO', expires_at: new Date(Date.now() + 60000).toISOString() }) }
    return json({ items: [] })
  }))
  render(<Providers><MemoryRouter><PhonesGroups /></MemoryRouter></Providers>)
  await act(async () => { await vi.advanceTimersByTimeAsync(10) })
  fireEvent.click(screen.getByRole('button', { name: 'Conectar WhatsApp' }))
  await act(async () => { await vi.advanceTimersByTimeAsync(10) })
  expect(screen.getByRole('img', { name: 'QR code de Principal' })).toHaveAttribute('src', 'data:image/png;base64,PRIMEIRO')
  // Deixe as respostas HTTP e notificações da query terminar em cada avanço.
  for (let elapsed = 0; elapsed < Math.min(validity, 30000) + 1000; elapsed += 1000) {
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
  }
  expect(qrCalls).toBe(1)
  expect(statusCalls).toBeGreaterThanOrEqual(3)
  expect(screen.getByRole('img', { name: 'QR code de Principal' })).toHaveAttribute('src', 'data:image/png;base64,NOVO')
  connected = true
  await act(async () => { await vi.advanceTimersByTimeAsync(4000) })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  const stopped = statusCalls
  await act(async () => { await vi.advanceTimersByTimeAsync(30000) })
  expect(statusCalls).toBe(stopped)
})

it('sincroniza token ausente e atualiza seu selo', async () => {
  let synced = false
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (path.endsWith('/token/sync')) { synced = true; return json({ ...phone, has_instance_token: true }) }
    if (path === '/api/phones') return json({ items: [{ ...phone, has_instance_token: synced }] })
    return json({ items: [] })
  }))
  render(<Providers><MemoryRouter><PhonesGroups /></MemoryRouter></Providers>)
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Sincronizar token' }))
  expect(await screen.findByText('Token da instância: OK')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Sincronizar token' })).not.toBeInTheDocument()
})

it('explica indisponibilidade do servidor ao conectar', async () => {
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (path.endsWith('/instance')) return json({ error: { code: 'SERVICE_UNAVAILABLE', message: 'evolution-api indisponível' } }, 503)
    if (path === '/api/phones') return json({ items: [phone] })
    return json({ items: [] })
  }))
  render(<Providers><MemoryRouter><PhonesGroups /></MemoryRouter></Providers>)
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Conectar WhatsApp' }))
  expect(await screen.findByText('Servidor do WhatsApp indisponível, tente de novo')).toBeInTheDocument()
})

it('pagina o histórico de execuções do bot', async () => {
  const urls: URL[] = []
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const url = new URL(request.url); urls.push(url)
    if (url.pathname === '/api/bots/bot-1') return json(bot)
    if (url.pathname === '/api/niches') return json([])
    if (url.pathname.endsWith('/runs')) {
      const page = Number(url.searchParams.get('page'))
      return json({ items: [{ id: page, started_at: '2026-10-13T12:00:00Z', kind: `Execução ${page}`, status: 'success', offers_found: 1, offers_sent: 1 }], total: 26, page, page_size: 25 })
    }
    if (url.pathname.endsWith('/health')) return json({ status: 'ok', message: 'Funcionando' })
    return json({ items: [] })
  }))
  render(<Providers><MemoryRouter initialEntries={['/bots/bot-1']}><Routes><Route path="/bots/:id" element={<BotDetail />} /></Routes></MemoryRouter></Providers>)
  expect(await screen.findByText('Execução 1')).toBeInTheDocument()
  await userEvent.setup().click(screen.getByRole('button', { name: 'Próxima' }))
  expect(await screen.findByText('Execução 2')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Próxima' })).toBeDisabled()
  expect(urls.filter(url => url.pathname.endsWith('/runs')).at(-1)?.searchParams.get('page')).toBe('2')
  await userEvent.setup().click(screen.getByRole('button', { name: 'Anterior' }))
  expect(await screen.findByText('Execução 1')).toBeInTheDocument()
})

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

it('cadastra por convite e atualiza a lista', async () => {
  const user = userEvent.setup()
  let added = false
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (path === '/api/groups/from-invite') {
      expect(await request.json()).toEqual({ phone_id: phone.id, invite_link: 'https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv' })
      added = true
      return json({ ...group, warning: null }, 201)
    }
    if (path === '/api/phones') return json({ items: [phone] })
    if (path === '/api/groups') return json({ items: added ? [{ ...group, warning: null }] : [] })
    return json({ items: [] })
  }))
  render(<Providers><MemoryRouter><PhonesGroups /></MemoryRouter></Providers>)
  await user.type(await screen.findByLabelText('Link de convite do grupo'), 'https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv')
  await user.click(screen.getByRole('button', { name: 'Adicionar' }))
  expect(await screen.findByText('Grupo cadastrado.')).toBeInTheDocument()
  expect(await screen.findByText('Promoções')).toBeInTheDocument()
})

it('mostra a mensagem da API ao recusar convite', async () => {
  const user = userEvent.setup()
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (path === '/api/groups/from-invite') return json({ error: { code: 'VALIDATION_ERROR', message: 'Convite inválido ou expirado' } }, 422)
    if (path === '/api/phones') return json({ items: [phone] })
    return json({ items: [] })
  }))
  render(<Providers><MemoryRouter><PhonesGroups /></MemoryRouter></Providers>)
  await user.type(await screen.findByLabelText('Link de convite do grupo'), 'inválido')
  await user.click(screen.getByRole('button', { name: 'Adicionar' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Convite inválido ou expirado')
})

function Destination() { return <span>{useLocation().pathname}</span> }

it('configura origem e vendas mínimas sem alterar o padrão dos bots existentes', async () => {
  const user = userEvent.setup()
  let saved: unknown
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (request.method === 'PATCH') { saved = await request.json(); return json(bot) }
    if (path === '/api/bots/bot-1') return json(bot)
    if (path === '/api/niches') return json([])
    if (path === '/api/phones') return json({ items: [phone] })
    if (path === '/api/groups') return json({ items: [group] })
    if (path === '/api/accounts' || path.endsWith('/runs') || path.endsWith('/config-backups')) return json({ items: [] })
    return json({ status: 'ok', message: 'Funcionando', credential_issues: [], group_issues: [] })
  }))
  render(<Providers><MemoryRouter initialEntries={['/bots/bot-1']}><Routes><Route path="/bots/:id" element={<BotDetail />} /></Routes></MemoryRouter></Providers>)
  const origin = await screen.findByRole('combobox', { name: /^Origem dos produtos/ })
  expect(origin).toHaveValue('novidades')
  expect(screen.queryByLabelText('Vendas mínimas (Shopee)')).not.toBeInTheDocument()
  await user.selectOptions(origin, 'mais_vendidos')
  const minimum = screen.getByLabelText('Vendas mínimas (Shopee)')
  expect(minimum).toHaveValue(100)
  expect(screen.getByText('Não se aplica aos mais vendidos.')).toBeInTheDocument()
  await user.clear(minimum)
  await user.type(minimum, '250')
  await user.selectOptions(origin, 'ambos')
  await user.click(screen.getByRole('button', { name: 'Salvar alterações' }))
  expect(await screen.findByText('Bot salvo.')).toBeInTheDocument()
  expect(saved).toMatchObject({ settings: { filters: { origem_produtos: 'ambos', min_vendas: 250 } } })
})

it('prioriza o Mercado Livre e grava a loja na frente sem mudar o revezamento padrão', async () => {
  const user = userEvent.setup()
  let saved: unknown
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (request.method === 'PATCH') { saved = await request.json(); return json(bot) }
    if (path === '/api/bots/bot-1') return json(bot)
    if (path === '/api/niches') return json([])
    if (path === '/api/phones') return json({ items: [phone] })
    if (path === '/api/groups') return json({ items: [group] })
    if (path === '/api/accounts' || path.endsWith('/runs') || path.endsWith('/config-backups')) return json({ items: [] })
    return json({ status: 'ok', message: 'Funcionando', credential_issues: [], group_issues: [] })
  }))
  render(<Providers><MemoryRouter initialEntries={['/bots/bot-1']}><Routes><Route path="/bots/:id" element={<BotDetail />} /></Routes></MemoryRouter></Providers>)
  const priority = await screen.findByRole('combobox', { name: /^Prioridade da loja/ })
  expect(priority).toHaveValue('alternar')
  await user.selectOptions(priority, 'mercado_livre')
  await user.click(screen.getByRole('button', { name: 'Salvar alterações' }))
  expect(await screen.findByText('Bot salvo.')).toBeInTheDocument()
  expect(saved).toMatchObject({ settings: { filters: { prioridade_loja: 'mercado_livre' } } })
})

it('liga o cupom de venda indireta sem mudar o padrão desligado', async () => {
  const user = userEvent.setup()
  let saved: unknown
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (request.method === 'PATCH') { saved = await request.json(); return json(bot) }
    if (path === '/api/bots/bot-1') return json(bot)
    if (path === '/api/niches') return json([])
    if (path === '/api/phones') return json({ items: [phone] })
    if (path === '/api/groups') return json({ items: [group] })
    if (path === '/api/accounts' || path.endsWith('/runs') || path.endsWith('/config-backups')) return json({ items: [] })
    return json({ status: 'ok', message: 'Funcionando', credential_issues: [], group_issues: [] })
  }))
  render(<Providers><MemoryRouter initialEntries={['/bots/bot-1']}><Routes><Route path="/bots/:id" element={<BotDetail />} /></Routes></MemoryRouter></Providers>)
  const coupon = await screen.findByRole('checkbox', { name: /Cupom de venda indireta/ })
  expect(coupon).not.toBeChecked()
  await user.click(coupon)
  await user.click(screen.getByRole('button', { name: 'Salvar alterações' }))
  expect(await screen.findByText('Bot salvo.')).toBeInTheDocument()
  expect(saved).toMatchObject({ settings: { content: { cupom_venda_indireta: true } } })
})

it('configura público e relevância, exibindo o limiar somente com público preenchido', async () => {
  const user = userEvent.setup()
  let saved: unknown
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (request.method === 'PATCH') { saved = await request.json(); return json(bot) }
    if (path === '/api/bots/bot-1') return json(bot)
    if (path === '/api/niches') return json([])
    if (path === '/api/phones') return json({ items: [phone] })
    if (path === '/api/groups') return json({ items: [group] })
    if (path === '/api/accounts' || path.endsWith('/runs') || path.endsWith('/config-backups')) return json({ items: [] })
    return json({ status: 'ok', message: 'Funcionando', credential_issues: [], group_issues: [] })
  }))
  render(<Providers><MemoryRouter initialEntries={['/bots/bot-1']}><Routes><Route path="/bots/:id" element={<BotDetail />} /></Routes></MemoryRouter></Providers>)
  const audience = await screen.findByRole('textbox', { name: /^Público do grupo/ })
  expect(audience).toHaveValue('')
  expect(audience).toHaveAttribute('maxlength', '500')
  expect(screen.queryByLabelText('Classificador')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Relevância mínima')).not.toBeInTheDocument()
  await user.type(audience, 'mulheres adultas')
  const classifier = screen.getByRole('combobox', { name: 'Classificador' })
  expect(classifier).toHaveValue('jev')
  await user.selectOptions(classifier, 'haiku')
  const minimum = screen.getByLabelText('Relevância mínima')
  expect(minimum).toHaveValue(0.6)
  expect(minimum).toHaveAttribute('min', '0')
  expect(minimum).toHaveAttribute('max', '1')
  expect(minimum).toHaveAttribute('step', '0.05')
  await user.clear(minimum)
  await user.type(minimum, '0.75')
  await user.click(screen.getByRole('button', { name: 'Salvar alterações' }))
  expect(await screen.findByText('Bot salvo.')).toBeInTheDocument()
  expect(saved).toMatchObject({ settings: { filters: { publico_alvo: 'mulheres adultas', classificador_publico: 'haiku', relevancia_minima: 0.75 } } })
  await user.clear(audience)
  expect(screen.queryByLabelText('Classificador')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Relevância mínima')).not.toBeInTheDocument()
})

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
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Mais ações de Bot Casa' }))
  await user.click(await screen.findByRole('menuitem', { name: 'Duplicar' }))
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
    if (path.endsWith('/config-backups')) return json({ items: [], total: 0, page: 1, page_size: 200 })
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
