import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, apiFailure } from '../api/client'
import type { components } from '../api/schema'
import { errorMessage } from '../api/management'
import { Field, Modal, StatusBadge } from '../components/Management'
import { Spinner } from '../components/Spinner'
import { useToast } from '../components/useToast'
import { formatBRL, formatDateTime, formatPercent } from '../lib/format'
import { normalizeMoneyInput } from '../lib/moneyInput'
import { useBillingRefresh } from './useBillingRefresh'

export type Plan = components['schemas']['PlanResponse']
type Tenant = components['schemas']['TenantResponse']
type SubscriptionUpdate = components['schemas']['SubscriptionUpdate']
const statuses = { trialing: 'Em teste', active: 'Ativa', past_due: 'Em atraso', canceled: 'Cancelada', comp: 'Cortesia' } as const
const eventNames: Record<components['schemas']['SubscriptionEventResponse']['type'], string> = { created: 'Criada', plan_changed: 'Plano alterado', price_changed: 'Preço alterado', status_changed: 'Assinatura atualizada', canceled: 'Cancelada', reactivated: 'Reativada' }

export function BillingMetrics({ enabled }: { enabled: boolean }) {
  const query = useQuery({ queryKey: ['platform-metrics'], enabled, queryFn: async () => {
    const result = await api.GET('/api/platform/metrics', { params: { query: { months: 12 } } })
    if (!result.data) throw apiFailure(result.error, result.response)
    return result.data
  } })
  if (query.isPending) return <Spinner label="Carregando métricas do SaaS" />
  if (query.isError) return <div className="page-error">{errorMessage(query.error)}</div>
  const { summary, months } = query.data
  const indicators = [
    ['MRR', formatBRL(summary.mrr)], ['Clientes pagantes', String(summary.paying)],
    ['Novos clientes', String(summary.new_tenants)], ['Cancelamentos', String(summary.churned)],
    ['Churn do mês', summary.churn_rate === null ? '—' : formatPercent(Number(summary.churn_rate))],
    ['Receita média por cliente (ARPA)', summary.arpa === null ? '—' : formatBRL(summary.arpa)],
  ]
  const chart = months.map((month) => ({ ...month, mrrValue: Number(month.mrr), label: month.mes.slice(0, 7).split('-').reverse().join('/') }))
  return <>
    <section aria-label="Indicadores do mês" className="kpi-grid platform-kpis">{indicators.map(([label, value]) => <article className="kpi-card" key={label}><p className="kpi-label">{label}</p><strong className="kpi-value">{value}</strong></article>)}</section>
    <p className="muted">Mês atual em Brasília. Contas internas ficam fora dos indicadores. Cancelamentos contam pagantes que saíram desde a abertura do mês, incluindo rebaixamentos para gratuito.</p>
    <section className="panel"><h2>MRR e clientes pagantes · últimos 12 meses</h2><div className="chart-wrap" role="img" aria-label="Gráfico mensal de MRR em barras e clientes pagantes em linha"><ResponsiveContainer width="100%" height={310}><ComposedChart data={chart} margin={{ top: 10, right: 12, left: 4, bottom: 5 }}>
      <CartesianGrid strokeDasharray="3 3" opacity={0.18} /><XAxis dataKey="label" /><YAxis yAxisId="mrr" tickFormatter={(value: number) => `R$ ${value}`} width={80} /><YAxis yAxisId="paying" orientation="right" allowDecimals={false} />
      <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 10 }} formatter={(value, name, item) => [name === 'MRR' ? formatBRL(item.payload.mrr) : String(value), name]} /><Legend />
      <Bar yAxisId="mrr" name="MRR" dataKey="mrrValue" fill="#2A9D6A" radius={[6, 6, 0, 0]} /><Line yAxisId="paying" name="Clientes pagantes" dataKey="paying_end" type="monotone" stroke="#6C74C9" strokeWidth={3} />
    </ComposedChart></ResponsiveContainer></div></section>
  </>
}

export function SubscriptionPanel({ tenant, plans, onClose }: { tenant: Tenant; plans: Plan[]; onClose: () => void }) {
  const sub = tenant.subscription
  const [planCode, setPlanCode] = useState(tenant.plan?.code || 'beta')
  const [status, setStatus] = useState<NonNullable<SubscriptionUpdate['status']>>(sub?.status || 'trialing')
  const [price, setPrice] = useState((sub?.price || plans.find((p) => p.code === planCode)?.price || '0.00').replace('.', ','))
  const [interval, setInterval] = useState<NonNullable<SubscriptionUpdate['interval']>>(sub?.interval || 'month')
  const [periodEnd, setPeriodEnd] = useState(sub?.current_period_end ? new Date(sub.current_period_end).toLocaleString('sv-SE', { timeZone: 'America/Sao_Paulo' }).slice(0, 16).replace(' ', 'T') : '')
  const [reason, setReason] = useState(sub?.cancel_reason || ''), [note, setNote] = useState(''), [priceError, setPriceError] = useState('')
  const refresh = useBillingRefresh(), { showToast } = useToast()
  const events = useQuery({ queryKey: ['subscription-events', tenant.id], queryFn: async () => {
    const result = await api.GET('/api/platform/tenants/{tenant_id}/subscription/events', { params: { path: { tenant_id: tenant.id } } })
    if (!result.data) throw apiFailure(result.error, result.response)
    return result.data
  } })
  const save = useMutation({ mutationFn: async (amount: string) => {
    const result = await api.PATCH('/api/platform/tenants/{tenant_id}/subscription', { params: { path: { tenant_id: tenant.id } }, body: { plan_code: planCode, status, price: amount, interval, current_period_end: periodEnd ? `${periodEnd}:00-03:00` : null, cancel_reason: status === 'canceled' ? reason : null, note: note || null } })
    if (!result.data) throw apiFailure(result.error, result.response)
  }, onSuccess: async () => { await refresh(); showToast('Assinatura atualizada.', 'success'); onClose() }, onError: (error) => showToast(errorMessage(error), 'error') })
  const changePlan = (code: string) => { setPlanCode(code); const plan = plans.find((p) => p.code === code); if (plan) { setPrice(plan.price.replace('.', ',')); setInterval(plan.interval) } }
  return <Modal title={`Assinatura · ${tenant.name}`} size="drawer" onClose={onClose}><form className="form-grid" onSubmit={(event) => { event.preventDefault(); const parsed = normalizeMoneyInput(price); if (!parsed.value) { setPriceError(parsed.error || 'Valor inválido'); return }; setPriceError(''); save.mutate(parsed.value) }}>
    <p className="muted">Registro manual. O status e os limites do plano não bloqueiam o uso do sistema.</p>
    <Field label="Plano"><select value={planCode} onChange={(event) => changePlan(event.target.value)}>{plans.filter((p) => p.is_active || p.code === planCode).map((plan) => <option key={plan.id} value={plan.code}>{plan.name}{!plan.is_active ? ' (inativo)' : ''}</option>)}</select></Field>
    <Field label="Status da assinatura"><select value={status} onChange={(event) => setStatus(event.target.value as typeof status)}>{Object.entries(statuses).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></Field>
    <Field label="Preço praticado (R$)" error={priceError}><input required inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} /></Field>
    <Field label="Periodicidade"><select value={interval} onChange={(event) => setInterval(event.target.value as typeof interval)}><option value="month">Mensal</option><option value="year">Anual</option></select></Field>
    <Field label="Fim do período (Brasília)"><input type="datetime-local" value={periodEnd} onChange={(event) => setPeriodEnd(event.target.value)} /></Field>
    {sub?.trial_ends_at && <p>Teste até {formatDateTime(sub.trial_ends_at)}</p>}
    {status === 'canceled' && <Field label="Motivo do cancelamento"><textarea required maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} /></Field>}
    <Field label="Nota do registro"><textarea maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} /></Field>
    <section className="subscription-history"><h3>Histórico de eventos</h3>{events.isPending ? <Spinner label="Carregando histórico" /> : events.isError ? <p role="alert">{errorMessage(events.error)}</p> : events.data.length === 0 ? <p>Sem eventos de assinatura.</p> : <ol>{events.data.map((entry) => <li key={entry.id}><strong>{eventNames[entry.type]}</strong><small>{formatDateTime(entry.occurred_at)}</small><div>{entry.status_before && <><StatusBadge value={entry.status_before} /> → </>}<StatusBadge value={entry.status_after} /></div><p>MRR: {formatBRL(entry.mrr_before)} → {formatBRL(entry.mrr_after)}</p>{entry.note && <p>{entry.note}</p>}</li>)}</ol>}</section>
    <div className="form-actions"><button type="button" className="button ghost" onClick={onClose}>Cancelar</button><button className="button primary" disabled={save.isPending || !planCode}>Salvar assinatura</button></div>
  </form></Modal>
}

export function PlanForm({ plan, onClose }: { plan: Plan | null; onClose: () => void }) {
  const [code, setCode] = useState(plan?.code || ''), [name, setName] = useState(plan?.name || '')
  const [price, setPrice] = useState(plan?.price.replace('.', ',') || '0,00'), [priceError, setPriceError] = useState('')
  const [interval, setInterval] = useState<Plan['interval']>(plan?.interval || 'month'), [active, setActive] = useState(plan?.is_active ?? true)
  const [bots, setBots] = useState(String(plan?.limits.max_bots ?? '')), [phones, setPhones] = useState(String(plan?.limits.max_phones ?? '')), [groups, setGroups] = useState(String(plan?.limits.max_groups ?? ''))
  const refresh = useBillingRefresh(), { showToast } = useToast()
  const save = useMutation({ mutationFn: async (amount: string) => {
    const limits: components['schemas']['PlanLimits'] = { ...(bots !== '' ? { max_bots: Number(bots) } : {}), ...(phones !== '' ? { max_phones: Number(phones) } : {}), ...(groups !== '' ? { max_groups: Number(groups) } : {}) }
    const values = { name, price: amount, limits, is_active: active }
    const result = plan ? await api.PATCH('/api/platform/plans/{plan_id}', { params: { path: { plan_id: plan.id } }, body: values }) : await api.POST('/api/platform/plans', { body: { ...values, code, currency: 'BRL', interval } })
    if (!result.data) throw apiFailure(result.error, result.response)
  }, onSuccess: async () => { await refresh(); showToast('Plano salvo.', 'success'); onClose() }, onError: (error) => showToast(errorMessage(error), 'error') })
  return <Modal title={plan ? `Editar plano · ${plan.name}` : 'Novo plano'} onClose={onClose}><form className="form-grid" onSubmit={(event) => { event.preventDefault(); const parsed = normalizeMoneyInput(price); if (!parsed.value) { setPriceError(parsed.error || 'Valor inválido'); return }; setPriceError(''); save.mutate(parsed.value) }}>
    <Field label="Código"><input required disabled={!!plan} pattern="[a-z0-9][a-z0-9_-]*" maxLength={80} value={code} onChange={(event) => setCode(event.target.value)} /></Field>
    <Field label="Nome do plano"><input required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} /></Field>
    <Field label="Preço do plano (R$)" error={priceError}><input required inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} /></Field>
    <Field label="Periodicidade"><select disabled={!!plan} value={interval} onChange={(event) => setInterval(event.target.value as Plan['interval'])}><option value="month">Mensal</option><option value="year">Anual</option></select></Field>
    <p className="muted">Alterar o preço do plano preserva os preços das assinaturas existentes. Limites vazios significam uso ilimitado.</p>
    <Field label="Máximo de bots"><input type="number" min={0} step={1} value={bots} onChange={(event) => setBots(event.target.value)} /></Field>
    <Field label="Máximo de telefones"><input type="number" min={0} step={1} value={phones} onChange={(event) => setPhones(event.target.value)} /></Field>
    <Field label="Máximo de grupos"><input type="number" min={0} step={1} value={groups} onChange={(event) => setGroups(event.target.value)} /></Field>
    <label className="check-field"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />Plano ativo para novas assinaturas</label>
    <div className="form-actions"><button type="button" className="button ghost" onClick={onClose}>Cancelar</button><button className="button primary" disabled={save.isPending}>Salvar plano</button></div>
  </form></Modal>
}
