import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Plus } from 'lucide-react'
import { api, apiFailure } from '../api/client'
import type { components } from '../api/schema'
import { errorMessage } from '../api/management'
import { useAuth } from '../auth/useAuth'
import { ConfirmButton, Field, Modal, StatusBadge } from '../components/Management'
import { Spinner } from '../components/Spinner'
import { useToast } from '../components/useToast'
import { formatBRL, formatDate } from '../lib/format'
import { BillingMetrics, PlanForm, SubscriptionPanel, type Plan } from './PlatformBilling'
import { useBillingRefresh } from './useBillingRefresh'

type Tenant = components['schemas']['TenantResponse']
type MirrorSources = components['schemas']['MirrorSourceGroupsResponse']

function TenantForm({ onClose, plans }: { onClose: () => void; plans: Plan[] }) {
  const refresh = useBillingRefresh(), { showToast } = useToast()
  const [name, setName] = useState(''), [adminName, setAdminName] = useState('')
  const [email, setEmail] = useState(''), [password, setPassword] = useState('')
  const [planCode, setPlanCode] = useState(plans.find((plan) => plan.code === 'beta' && plan.is_active)?.code || plans.find((plan) => plan.is_active)?.code || ''), [status, setStatus] = useState<components['schemas']['TenantCreate']['status']>('trialing')
  const save = useMutation({ mutationFn: async () => {
    const result = await api.POST('/api/platform/tenants', { body: { name, admin_name: adminName, admin_email: email, admin_password: password, plan_code: planCode, status } })
    if (!result.data) throw apiFailure(result.error, result.response)
  }, onSuccess: async () => { setPassword(''); await refresh(); showToast('Conta criada.', 'success'); onClose() }, onError: (error) => showToast(errorMessage(error), 'error') })
  return <Modal title="Nova conta de cliente" onClose={onClose}><form className="form-grid" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
    <Field label="Nome da conta"><input required value={name} onChange={(event) => setName(event.target.value)} /></Field>
    <Field label="Nome do administrador"><input required value={adminName} onChange={(event) => setAdminName(event.target.value)} /></Field>
    <Field label="E-mail do administrador"><input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></Field>
    <Field label="Senha do administrador"><input required minLength={8} type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></Field>
    <Field label="Plano"><select required value={planCode} onChange={(event) => setPlanCode(event.target.value)}>{plans.filter((plan) => plan.is_active).map((plan) => <option value={plan.code} key={plan.id}>{plan.name} · {formatBRL(plan.price)} / {plan.interval === 'year' ? 'ano' : 'mês'}</option>)}</select></Field>
    <Field label="Status inicial"><select value={status} onChange={(event) => setStatus(event.target.value as typeof status)}><option value="trialing">Em teste por 14 dias</option><option value="active">Ativa</option><option value="comp">Cortesia</option></select></Field>
    <div className="form-actions"><button type="button" className="button ghost" onClick={onClose}>Cancelar</button><button className="button primary" disabled={save.isPending || !planCode}>Criar conta</button></div>
  </form></Modal>
}

function MirrorSourcesPanel() {
  const { showToast } = useToast()
  const queryClient = useQueryClient()
  const sources = useQuery({
    queryKey: ['platform-mirror-sources'],
    queryFn: async () => {
      const result = await api.GET('/api/platform/mirror/source-groups')
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data as MirrorSources
    },
  })
  const [selected, setSelected] = useState<string[]>([])
  useEffect(() => {
    if (sources.data) setSelected(sources.data.selected.slice(0, sources.data.max_selected))
  }, [sources.data])
  const max = sources.data?.max_selected ?? 3
  const save = useMutation({
    mutationFn: async () => {
      const result = await api.PUT('/api/platform/mirror/source-groups', { body: { names: selected, reset_to_default: false } })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data as MirrorSources
    },
    onSuccess: async (data) => {
      await queryClient.invalidateQueries({ queryKey: ['platform-mirror-sources'] })
      const skipped = data.pending_skipped ?? 0
      showToast(skipped > 0 ? `Origens salvas. ${skipped} pendente(s) fora da lista saíram da fila.` : 'Origens da escuta salvas.', 'success')
    },
    onError: (error) => showToast(errorMessage(error), 'error'),
  })
  const reset = useMutation({
    mutationFn: async () => {
      const result = await api.PUT('/api/platform/mirror/source-groups', { body: { names: [], reset_to_default: true } })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data as MirrorSources
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['platform-mirror-sources'] })
      showToast('Voltou ao padrão/env da plataforma.', 'success')
    },
    onError: (error) => showToast(errorMessage(error), 'error'),
  })
  if (sources.isLoading) return <Spinner label="Carregando origens" />
  if (sources.isError || !sources.data) return <div className="page-error">{errorMessage(sources.error)}</div>
  const toggleName = (name: string) => {
    setSelected((current) => {
      if (current.includes(name)) return current.filter((item) => item !== name)
      if (current.length >= max) return current
      return [...current, name]
    })
  }
  return <section className="panel">
    <h2>Grupos de origem (escuta)</h2>
    <p>A Nina 1 só espelha estes grupos. No máximo {max} — menos origem = fila mais curta e cupom chega a tempo. Fonte atual: {sources.data.source === 'database' ? 'dashboard' : sources.data.source === 'env' ? 'variável de ambiente' : 'padrão do código'}.</p>
    <div className="selection-columns"><fieldset><legend>Escolha até {max}</legend>
      {sources.data.candidates.map((name) => {
        const checked = selected.includes(name)
        const blocked = !checked && selected.length >= max
        return <label className="check" key={name}><input type="checkbox" checked={checked} disabled={blocked || save.isPending} onChange={() => toggleName(name)} />{name}</label>
      })}
    </fieldset></div>
    <p className="muted">{selected.length} / {max} selecionados. Pending dos grupos desmarcados saem da fila ao salvar.</p>
    <div className="form-actions">
      <ConfirmButton className="button ghost" question="Voltar ao padrão/env? Pode reabrir todos os grupos do catálogo." onConfirm={() => reset.mutate()}>Restaurar padrão</ConfirmButton>
      <button className="button primary" disabled={save.isPending || selected.length < 1 || selected.length > max} onClick={() => save.mutate()}>Salvar origens</button>
    </div>
  </section>
}

export function Platform() {
  const { user } = useAuth(), { showToast } = useToast(), queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Tenant | null>(null), [editingPlan, setEditingPlan] = useState<Plan | null | undefined>(undefined)
  const [tab, setTab] = useState<'tenants' | 'plans' | 'mirror'>('tenants')
  const plans = useQuery({ queryKey: ['platform-plans'], enabled: !!user?.is_platform_admin, queryFn: async () => {
    const result = await api.GET('/api/platform/plans')
    if (!result.data) throw apiFailure(result.error, result.response)
    return result.data
  } })
  const tenants = useQuery({ queryKey: ['platform-tenants'], enabled: !!user?.is_platform_admin, queryFn: async () => {
    const result = await api.GET('/api/platform/tenants')
    if (!result.data) throw apiFailure(result.error, result.response)
    return result.data
  } })
  const toggle = useMutation({ mutationFn: async (tenant: Tenant) => {
    const result = await api.PATCH('/api/platform/tenants/{tenant_id}', { params: { path: { tenant_id: tenant.id } }, body: { status: tenant.status === 'active' ? 'suspended' : 'active' } })
    if (!result.data) throw apiFailure(result.error, result.response)
  }, onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['platform-tenants'] }); showToast('Conta atualizada.', 'success') }, onError: (error) => showToast(errorMessage(error), 'error') })
  if (!user?.is_platform_admin) return <div className="page-error"><h2>Acesso restrito</h2><p>Somente administradores da plataforma podem gerenciar contas.</p></div>
  if (tenants.isLoading) return <Spinner label="Carregando contas" />
  return <div><div className="page-heading"><div><h1>Plataforma</h1><p>Contas, assinaturas e desempenho do Nina Bot.</p></div><button className="button primary" disabled={!plans.data?.some((plan) => plan.is_active)} onClick={() => setCreating(true)}><Plus />Nova conta de cliente</button></div>
    <BillingMetrics enabled={!!user.is_platform_admin} />
    <div className="table-actions platform-tabs" role="tablist" aria-label="Gestão da plataforma"><button role="tab" aria-selected={tab === 'tenants'} className={`button ${tab === 'tenants' ? 'primary' : 'ghost'}`} onClick={() => setTab('tenants')}>Contas</button><button role="tab" aria-selected={tab === 'plans'} className={`button ${tab === 'plans' ? 'primary' : 'ghost'}`} onClick={() => setTab('plans')}>Planos</button><button role="tab" aria-selected={tab === 'mirror'} className={`button ${tab === 'mirror' ? 'primary' : 'ghost'}`} onClick={() => setTab('mirror')}>Espelho</button></div>
    {tenants.isError && <div className="page-error">{errorMessage(tenants.error)}</div>}{plans.isError && <div className="page-error">{errorMessage(plans.error)}</div>}
    {tab === 'tenants' ? <div className="responsive-table"><table><thead><tr><th>Conta</th><th>Plano</th><th>Assinatura</th><th>MRR</th><th>Uso / limite</th><th>Criada em</th><th>Envios (30 dias)</th><th>Ações</th></tr></thead><tbody>{tenants.data?.map((tenant) => <tr key={tenant.id}>
      <td data-label="Conta"><strong>{tenant.name}</strong>{tenant.is_internal && <small className="status-badge">Interna</small>}<small><StatusBadge value={tenant.status} /></small></td><td data-label="Plano">{tenant.plan?.name || '—'}</td><td data-label="Assinatura">{tenant.subscription ? <StatusBadge value={tenant.subscription.status} /> : '—'}</td><td data-label="MRR">{tenant.is_internal ? '—' : formatBRL(tenant.mrr)}</td>
      <td data-label="Uso / limite">{([['bots', 'bots', 'max_bots'], ['phones', 'telefones', 'max_phones'], ['groups', 'grupos', 'max_groups']] as const).map(([key, label, limit]) => <small key={key}>{tenant.usage?.[key] ?? 0} / {tenant.plan?.limits[limit] ?? '∞'} {label}</small>)}</td><td data-label="Criada em">{formatDate(tenant.created_at)}</td><td data-label="Envios (30 dias)">{tenant.successful_sends_30d}</td>
      <td data-label="Ações"><div className="table-actions">{!tenant.is_internal && <button className="button ghost" disabled={!plans.data} onClick={() => setEditing(tenant)}>Editar assinatura</button>}{tenant.id !== user.tenant.id && !toggle.isPending && <ConfirmButton question={tenant.status === 'active' ? `Suspender ${tenant.name}? Os bots ativos serão pausados e o acesso será bloqueado.` : `Reativar ${tenant.name}? Os bots continuarão pausados.`} onConfirm={() => toggle.mutate(tenant)}>{tenant.status === 'active' ? 'Suspender' : 'Reativar'}</ConfirmButton>}</div></td>
    </tr>)}</tbody></table></div> : tab === 'plans' ? <section className="panel"><div className="page-heading"><h2>Planos</h2><button className="button primary" onClick={() => setEditingPlan(null)}><Plus />Novo plano</button></div>{plans.isPending ? <Spinner label="Carregando planos" /> : <div className="responsive-table"><table><thead><tr><th>Plano</th><th>Preço</th><th>Limites</th><th>Status</th><th>Ações</th></tr></thead><tbody>{plans.data?.map((plan) => <tr key={plan.id}><td data-label="Plano">{plan.name}<small>{plan.code}</small></td><td data-label="Preço">{formatBRL(plan.price)} / {plan.interval === 'year' ? 'ano' : 'mês'}</td><td data-label="Limites">{plan.limits.max_bots ?? '∞'} bots · {plan.limits.max_phones ?? '∞'} telefones · {plan.limits.max_groups ?? '∞'} grupos</td><td data-label="Status"><StatusBadge value={plan.is_active ? 'active' : 'disabled'} /></td><td data-label="Ações"><button className="button ghost" onClick={() => setEditingPlan(plan)}>Editar plano</button></td></tr>)}</tbody></table></div>}</section> : <MirrorSourcesPanel />}
    {creating && <TenantForm plans={plans.data || []} onClose={() => setCreating(false)} />}{editing && <SubscriptionPanel tenant={editing} plans={plans.data || []} onClose={() => setEditing(null)} />}{editingPlan !== undefined && <PlanForm plan={editingPlan} onClose={() => setEditingPlan(undefined)} />}
  </div>
}
