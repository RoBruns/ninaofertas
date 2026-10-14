import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { cloneElement, type ReactElement, type ReactNode } from 'react'
import type { User } from '../api/client'
import type { components } from '../api/schema'
import { AuthContext, type AuthContextValue } from '../auth/AuthContext'
import { ToastProvider } from '../components/Toast'
import { Sidebar } from '../components/Sidebar'
import { Platform } from './Platform'
import { PhonesGroups } from './PhonesGroups'

vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return { ...actual, ResponsiveContainer: ({ children }: { children: ReactElement }) => <div>{cloneElement(children, { width: 600, height: 310 } as Record<string, number>)}</div> }
})

const plan: components['schemas']['PlanResponse'] = { id: 'plan-pro', code: 'pro', name: 'Pro', price: '150.00', currency: 'BRL', interval: 'month', limits: { max_bots: 3, max_phones: 1 }, is_active: true, created_at: '2026-10-01T12:00:00Z' }
const tenant: components['schemas']['TenantResponse'] = { id: 'cliente-a', name: 'Conta A', status: 'active', is_internal: false, created_at: '2026-10-14T10:00:00Z', users_count: 1, active_bots_count: 2, successful_sends_30d: 42, plan, subscription: { id: 'sub-a', tenant_id: 'cliente-a', plan_id: plan.id, status: 'active', price: '150.00', interval: 'month', started_at: '2026-10-01T12:00:00Z', current_period_start: '2026-10-01T12:00:00Z', current_period_end: null, trial_ends_at: null, canceled_at: null, cancel_reason: null, created_at: '2026-10-01T12:00:00Z', updated_at: '2026-10-01T12:00:00Z' }, mrr: '150.00', usage: { bots: 2, phones: 1, groups: 4 } }
const metrics: components['schemas']['BillingMetricsResponse'] = { summary: { mrr: '450.00', paying: 3, new_tenants: 2, churned: 1, churn_rate: null, arpa: '150.00' }, months: [{ mes: '2026-10-01', mrr: '450.00', paying_start: 0, paying_end: 3, new_tenants: 2, new_paying: 3, churned: 0, churn_rate: null, expansion_mrr: '0.00', contraction_mrr: '0.00', arpa: '150.00' }] }

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
    if (new URL(request.url).pathname === '/api/platform/metrics') return json(metrics)
    if (new URL(request.url).pathname === '/api/platform/plans') return json([plan])
    if (request.method === 'PATCH') { const body = await request.json() as { status: string }; writes.push(body); status = body.status; return json({ id: 'cliente-a', status }) }
    return json([{ ...tenant, status }])
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

it('renderiza os seis indicadores, churn nulo e uso; interna não tem ação de assinatura', async () => {
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (path.endsWith('/metrics')) return json(metrics)
    if (path.endsWith('/plans')) return json([plan])
    return json([tenant, { ...tenant, id: 'interna', name: 'Nina interna', is_internal: true, plan: null, subscription: null }])
  }))
  renderPage(<Platform />, true)
  const indicators = await screen.findByRole('region', { name: 'Indicadores do mês' })
  for (const [label, value] of [['MRR', 'R$ 450,00'], ['Clientes pagantes', '3'], ['Novos clientes', '2'], ['Cancelamentos', '1'], ['Churn do mês', '—'], ['Receita média por cliente (ARPA)', 'R$ 150,00']]) {
    expect(within(within(indicators).getByText(label).closest('article')!).getByText(value)).toBeInTheDocument()
  }
  expect(screen.getAllByText('2 / 3 bots')).toHaveLength(1)
  expect(screen.getAllByText('4 / ∞ grupos')).toHaveLength(2)
  const internal = screen.getByText('Nina interna').closest('tr')!
  expect(within(internal).getByText('Interna')).toBeInTheDocument()
  expect(within(internal).queryByRole('button', { name: 'Editar assinatura' })).not.toBeInTheDocument()
  expect(screen.getByRole('img', { name: /Gráfico mensal de MRR/ })).toBeInTheDocument()
})

it('edita assinatura no painel, exibe histórico e exige motivo para cancelar', async () => {
  const writes: unknown[] = []
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (request.method === 'PATCH') { writes.push(await request.json()); return json(tenant.subscription) }
    if (path.endsWith('/metrics')) return json(metrics)
    if (path.endsWith('/plans')) return json([plan])
    if (path.endsWith('/events')) return json([{ id: 1, type: 'created', status_before: null, status_after: 'active', mrr_before: '0.00', mrr_after: '150.00', occurred_at: '2026-10-01T12:00:00Z', note: writes.length ? 'Atendimento registrado' : 'Primeiro contrato' }])
    return json([tenant])
  }))
  renderPage(<Platform />, true)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Editar assinatura' }))
  const dialog = screen.getByRole('dialog', { name: 'Assinatura · Conta A' })
  expect(await within(dialog).findByText('Primeiro contrato')).toBeInTheDocument()
  await user.selectOptions(within(dialog).getByLabelText('Status da assinatura'), 'canceled')
  await user.click(within(dialog).getByRole('button', { name: 'Salvar assinatura' }))
  expect(writes).toHaveLength(0)
  await user.type(within(dialog).getByLabelText('Motivo do cancelamento'), 'Pausa solicitada')
  await user.type(within(dialog).getByLabelText('Nota do registro'), 'Atendimento')
  await user.clear(within(dialog).getByLabelText('Preço praticado (R$)'))
  await user.type(within(dialog).getByLabelText('Preço praticado (R$)'), '149,90')
  await user.click(within(dialog).getByRole('button', { name: 'Salvar assinatura' }))
  await waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0]).toEqual({ plan_code: 'pro', status: 'canceled', price: '149.90', interval: 'month', current_period_end: null, cancel_reason: 'Pausa solicitada', note: 'Atendimento' })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Editar assinatura' }))
  expect(await screen.findByText('Atendimento registrado')).toBeInTheDocument()
})

it('cria e edita plano enviando strings decimais e omite limites vazios', async () => {
  const writes: Array<{ method: string; body: unknown }> = []
  vi.stubGlobal('fetch', vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (request.method !== 'GET') { writes.push({ method: request.method, body: await request.json() }); return json(plan) }
    if (path.endsWith('/metrics')) return json(metrics)
    if (path.endsWith('/plans')) return json([plan])
    return json([tenant])
  }))
  renderPage(<Platform />, true)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('tab', { name: 'Planos' }))
  await user.click(screen.getByRole('button', { name: 'Novo plano' }))
  await user.type(screen.getByLabelText('Código'), 'anual')
  await user.type(screen.getByLabelText('Nome do plano'), 'Anual')
  await user.clear(screen.getByLabelText('Preço do plano (R$)'))
  await user.type(screen.getByLabelText('Preço do plano (R$)'), '1.200,00')
  await user.selectOptions(screen.getByLabelText('Periodicidade'), 'year')
  await user.type(screen.getByLabelText('Máximo de bots'), '5')
  await user.click(screen.getByRole('button', { name: 'Salvar plano' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(writes[0]).toEqual({ method: 'POST', body: { code: 'anual', name: 'Anual', price: '1200.00', currency: 'BRL', interval: 'year', limits: { max_bots: 5 }, is_active: true } })
  await user.click(screen.getByRole('button', { name: 'Editar plano' }))
  await user.clear(screen.getByLabelText('Máximo de bots'))
  await user.click(screen.getByRole('button', { name: 'Salvar plano' }))
  await waitFor(() => expect(writes).toHaveLength(2))
  expect(writes[1]).toEqual({ method: 'PATCH', body: { name: 'Pro', price: '150.00', limits: { max_phones: 1 }, is_active: true } })
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
