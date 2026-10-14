import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Plus } from 'lucide-react'
import { api, apiFailure } from '../api/client'
import type { components } from '../api/schema'
import { errorMessage } from '../api/management'
import { useAuth } from '../auth/useAuth'
import { ConfirmButton, Field, Modal, StatusBadge } from '../components/Management'
import { Spinner } from '../components/Spinner'
import { useToast } from '../components/useToast'

type Tenant = components['schemas']['TenantResponse']

function TenantForm({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient(), { showToast } = useToast()
  const [name, setName] = useState(''), [adminName, setAdminName] = useState('')
  const [email, setEmail] = useState(''), [password, setPassword] = useState('')
  const save = useMutation({ mutationFn: async () => {
    const result = await api.POST('/api/platform/tenants', { body: { name, admin_name: adminName, admin_email: email, admin_password: password } })
    if (!result.data) throw apiFailure(result.error, result.response)
  }, onSuccess: async () => { setPassword(''); await queryClient.invalidateQueries({ queryKey: ['platform-tenants'] }); showToast('Conta criada.', 'success'); onClose() }, onError: (error) => showToast(errorMessage(error), 'error') })
  return <Modal title="Nova conta de cliente" onClose={onClose}><form className="form-grid" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
    <Field label="Nome da conta"><input required value={name} onChange={(event) => setName(event.target.value)} /></Field>
    <Field label="Nome do administrador"><input required value={adminName} onChange={(event) => setAdminName(event.target.value)} /></Field>
    <Field label="E-mail do administrador"><input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></Field>
    <Field label="Senha do administrador"><input required minLength={8} type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></Field>
    <div className="form-actions"><button type="button" className="button ghost" onClick={onClose}>Cancelar</button><button className="button primary" disabled={save.isPending}>Criar conta</button></div>
  </form></Modal>
}

export function Platform() {
  const { user } = useAuth(), { showToast } = useToast(), queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
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
  return <div><div className="page-heading"><div><h1>Plataforma</h1><p>Contas e uso do Nina Bot.</p></div><button className="button primary" onClick={() => setCreating(true)}><Plus />Nova conta de cliente</button></div>
    {tenants.isError && <div className="page-error">{errorMessage(tenants.error)}</div>}
    <div className="responsive-table"><table><thead><tr><th>Conta</th><th>Status</th><th>Criada em</th><th>Usuários</th><th>Bots ativos</th><th>Envios (30 dias)</th><th>Ações</th></tr></thead><tbody>{tenants.data?.map((tenant) => <tr key={tenant.id}>
      <td data-label="Conta"><strong>{tenant.name}</strong>{tenant.is_internal && <small>Interna</small>}</td><td data-label="Status"><StatusBadge value={tenant.status} /></td><td data-label="Criada em">{new Date(tenant.created_at).toLocaleDateString('pt-BR')}</td>
      <td data-label="Usuários">{tenant.users_count}</td><td data-label="Bots ativos">{tenant.active_bots_count}</td><td data-label="Envios (30 dias)">{tenant.successful_sends_30d}</td>
      <td data-label="Ações">{tenant.id !== user.tenant.id && !toggle.isPending && <ConfirmButton question={tenant.status === 'active' ? `Suspender ${tenant.name}? Os bots ativos serão pausados e o acesso será bloqueado.` : `Reativar ${tenant.name}? Os bots continuarão pausados.`} onConfirm={() => toggle.mutate(tenant)}>{tenant.status === 'active' ? 'Suspender' : 'Reativar'}</ConfirmButton>}</td>
    </tr>)}</tbody></table></div>{creating && <TenantForm onClose={() => setCreating(false)} />}
  </div>
}
