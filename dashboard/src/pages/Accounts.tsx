import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent } from 'react'
import { api, apiFailure, ApiError } from '../api/client'
import type { Account, AccountCreate, Platform } from '../api/management'
import { errorMessage } from '../api/management'
import { useAuth } from '../auth/useAuth'
import { ConfirmButton, Field, Modal, StatusBadge } from '../components/Management'
import { EmptyState } from '../components/EmptyState'
import { Spinner } from '../components/Spinner'
import { useToast } from '../components/useToast'

function conflictBots(value: unknown): string[] {
  if (Array.isArray(value)) return value.flatMap((item) => {
    if (typeof item === 'string') return [item]
    if (typeof item === 'object' && item !== null) {
      const record = item as Record<string, unknown>
      return typeof record.name === 'string' ? [record.name] : []
    }
    return []
  })
  if (typeof value !== 'object' || value === null) return []
  return Object.entries(value as Record<string, unknown>).flatMap(([key, item]) => key === 'bots' ? conflictBots(item) : conflictBots(item))
}

async function loadAccounts() {
  const { data, error, response } = await api.GET('/api/accounts', { params: { query: { page: 1, page_size: 100, sort: 'label' } } })
  if (!data) throw apiFailure(error, response)
  return data.items
}

async function loadPlatforms() {
  const { data, error, response } = await api.GET('/api/platforms')
  if (!data) throw apiFailure(error, response)
  return data
}

function AccountForm({ platforms, account, onClose }: { platforms: Platform[]; account?: Account; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [label, setLabel] = useState(account?.label ?? '')
  const [platformId, setPlatformId] = useState(account?.platform.id ?? platforms[0]?.id ?? 0)
  const [externalId, setExternalId] = useState(account?.external_id ?? '')
  const [notes, setNotes] = useState(account?.notes ?? '')
  const [configRows, setConfigRows] = useState(() => Object.entries(account?.config ?? {}).map(([key, value]) => ({ key, value: String(value) })))
  const [fields, setFields] = useState<Readonly<Record<string, string>>>({})
  const save = useMutation({ mutationFn: async () => {
    const config = Object.fromEntries(configRows.filter((row) => row.key.trim()).map((row) => [row.key.trim(), row.value]))
    if (account) {
      const { data, error, response } = await api.PATCH('/api/accounts/{account_id}', { params: { path: { account_id: account.id } }, body: { label, external_id: externalId || null, notes: notes || null, config } })
      if (!data) throw apiFailure(error, response)
      return data
    }
    const body: AccountCreate = { platform_id: platformId, label, external_id: externalId || null, notes: notes || null, config }
    const { data, error, response } = await api.POST('/api/accounts', { body })
    if (!data) throw apiFailure(error, response)
    return data
  }, onSuccess: async () => {
    await queryClient.invalidateQueries({ queryKey: ['accounts'] })
    showToast(account ? 'Conta atualizada.' : 'Conta criada.', 'success')
    onClose()
  }, onError: (error) => { setFields(error instanceof ApiError ? error.fields : {}); showToast(errorMessage(error), 'error') } })
  const submit = (event: FormEvent) => { event.preventDefault(); setFields({}); save.mutate() }
  return <Modal title={account ? 'Editar conta' : 'Nova conta'} onClose={onClose}><form className="form-grid" onSubmit={submit}>{!account && <Field label="Plataforma" error={fields.platform_id}><select value={platformId} onChange={(event) => setPlatformId(Number(event.target.value))}>{platforms.map((platform) => <option value={platform.id} key={platform.id}>{platform.name}</option>)}</select></Field>}<Field label="Rótulo" error={fields.label}><input required value={label} onChange={(event) => setLabel(event.target.value)} /></Field><Field label="ID externo" error={fields.external_id}><input value={externalId} onChange={(event) => setExternalId(event.target.value)} /></Field><Field label="Observações" error={fields.notes}><textarea value={notes} onChange={(event) => setNotes(event.target.value)} /></Field><fieldset className="config-editor"><legend>Configuração não sensível</legend>{configRows.map((row, index) => <div className="config-row" key={`${index}-${row.key}`}><input aria-label="Chave" placeholder="chave" value={row.key} onChange={(event) => setConfigRows(configRows.map((item, itemIndex) => itemIndex === index ? { ...item, key: event.target.value } : item))} /><input aria-label="Valor" placeholder="valor" value={row.value} onChange={(event) => setConfigRows(configRows.map((item, itemIndex) => itemIndex === index ? { ...item, value: event.target.value } : item))} /><button className="icon-button" type="button" aria-label="Remover configuração" onClick={() => setConfigRows(configRows.filter((_, itemIndex) => itemIndex !== index))}>×</button></div>)}<button className="button ghost" type="button" onClick={() => setConfigRows([...configRows, { key: '', value: '' }])}>Adicionar configuração</button></fieldset><div className="form-actions"><button className="button ghost" type="button" onClick={onClose}>Cancelar</button><button className="button primary" disabled={save.isPending}>Salvar</button></div></form></Modal>
}

function CredentialRenewal({ account, kind, newCredential = account.credentials.length === 0, onClose }: { account: Account; kind: string; newCredential?: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [credentialKind, setCredentialKind] = useState(kind)
  const [value, setValue] = useState('')
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [pending, setPending] = useState(false)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const secret = value
    setValue('')
    setResult(null)
    setPending(true)
    try {
      const put = await api.PUT('/api/accounts/{account_id}/credentials/{kind}', { params: { path: { account_id: account.id, kind: credentialKind } }, body: { value: secret } })
      if (put.response.status !== 204) throw apiFailure(put.error, put.response)
      const tested = await api.POST('/api/accounts/{account_id}/credentials/{kind}/test', { params: { path: { account_id: account.id, kind: credentialKind } } })
      if (!tested.data) throw apiFailure(tested.error, tested.response)
      setResult({ ok: tested.data.ok, message: tested.data.message })
    } catch (error) {
      setResult({ ok: false, message: errorMessage(error) })
    } finally {
      setPending(false)
      await queryClient.invalidateQueries({ queryKey: ['accounts'] })
    }
  }
  return <Modal title={`${newCredential ? 'Cadastrar' : 'Renovar'} ${credentialKind} — ${account.label}`} onClose={onClose}><form className="form-grid" onSubmit={(event) => void submit(event)}><p className="security-note">O valor é enviado uma única vez e não será exibido nem guardado pelo dashboard.</p>{newCredential && <Field label="Tipo de credencial"><select value={credentialKind} onChange={(event) => setCredentialKind(event.target.value)}><option value="cookie">Cookie</option><option value="token">Token</option></select></Field>}<Field label="Novo cookie ou token"><textarea aria-label="Novo cookie ou token" required autoComplete="off" spellCheck={false} value={value} onChange={(event) => setValue(event.target.value)} /></Field>{pending && <p>Salvando e testando…</p>}{result && <div className={result.ok ? 'inline-success' : 'inline-error'} role="status"><strong>{result.ok ? 'Funcionou' : 'Não funcionou'}</strong><span>{result.message}</span></div>}<div className="form-actions"><button className="button ghost" type="button" onClick={onClose}>Fechar</button><button className="button primary" disabled={pending || !value.trim()}>Salvar e testar</button></div></form></Modal>
}

export function Accounts() {
  const { user } = useAuth()
  const editable = user?.role === 'admin'
  const { showToast } = useToast()
  const queryClient = useQueryClient()
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: loadAccounts })
  const platforms = useQuery({ queryKey: ['platforms'], queryFn: loadPlatforms })
  const [editing, setEditing] = useState<Account | 'new' | null>(null)
  const [renewing, setRenewing] = useState<{ account: Account; kind: string; newCredential?: boolean } | null>(null)
  const [blockedBots, setBlockedBots] = useState<string[]>([])
  const action = useMutation({ mutationFn: async ({ account, operation }: { account: Account; operation: 'activate' | 'pause' | 'delete' }) => {
    if (operation === 'delete') {
      const result = await api.DELETE('/api/accounts/{account_id}', { params: { path: { account_id: account.id } } })
      if (result.response.status !== 204) throw apiFailure(result.error, result.response)
      return
    }
    const result = operation === 'activate'
      ? await api.POST('/api/accounts/{account_id}/activate', { params: { path: { account_id: account.id } } })
      : await api.POST('/api/accounts/{account_id}/pause', { params: { path: { account_id: account.id } } })
    if (!result.data) throw apiFailure(result.error, result.response)
  }, onSuccess: async () => { setBlockedBots([]); await queryClient.invalidateQueries({ queryKey: ['accounts'] }); showToast('Conta atualizada.', 'success') }, onError: (error) => {
    if (error instanceof ApiError && error.status === 409) setBlockedBots(conflictBots(error.details))
    showToast(errorMessage(error), 'error')
  } })
  const grouped = useMemo(() => {
    const result: Record<string, Account[]> = {}
    for (const account of [...(accounts.data ?? [])].sort((a, b) => Number(b.credentials.some((credential) => credential.needs_renewal)) - Number(a.credentials.some((credential) => credential.needs_renewal)))) {
      const platformAccounts = result[account.platform.name] ?? []
      result[account.platform.name] = [...platformAccounts, account]
    }
    return Object.entries(result)
  }, [accounts.data])
  if (accounts.isLoading || platforms.isLoading) return <Spinner label="Carregando contas" />
  return <div><div className="page-heading"><div><p className="eyebrow">PLATAFORMAS</p><h1>Contas</h1><p>Credenciais e contas afiliadas em um só lugar.</p></div>{editable && <button className="button primary" onClick={() => setEditing('new')}>Nova conta</button>}</div>{blockedBots.length > 0 && <div className="inline-error" role="alert"><strong>Esta conta está em uso e não pode ser excluída.</strong><span>Bots vinculados: {blockedBots.join(', ')}</span></div>}{accounts.isError && <div className="page-error">{errorMessage(accounts.error)}</div>}{!accounts.data?.length ? <EmptyState title="Nenhuma conta" description="Cadastre a primeira conta de plataforma." /> : <div className="management-groups">{grouped.map(([platform, items]) => <section key={platform}><h2>{platform}</h2><div className="card-list">{items?.map((account) => <article className={`management-card ${account.credentials.some((credential) => credential.needs_renewal) ? 'needs-attention' : ''}`} key={account.id}><div className="card-title"><div><h3>{account.label}</h3><small>{account.external_id || 'Sem ID externo'}</small></div><StatusBadge value={account.status} /></div><p className={`health health-${account.health.status}`}>{account.health.message || 'Saúde desconhecida'}</p>{account.credentials.length === 0 && <p className="muted">Nenhuma credencial cadastrada.</p>}{account.credentials.map((credential) => <div className="credential-row" key={credential.kind}><div><strong>{credential.kind}</strong> <StatusBadge value={credential.status} />{credential.needs_renewal && <span className="renewal-flag">Renovação necessária</span>}<small>{credential.last_error}</small></div>{editable && <button className="button ghost" onClick={() => setRenewing({ account, kind: credential.kind })}>Renovar credencial</button>}</div>)}{editable && account.credentials.length === 0 && <button className="button ghost" onClick={() => setRenewing({ account, kind: 'cookie' })}>Cadastrar credencial</button>}<div className="card-actions">{editable && <><button className="button ghost" onClick={() => setEditing(account)}>Editar</button><button className="button ghost" onClick={() => action.mutate({ account, operation: account.status === 'active' ? 'pause' : 'activate' })}>{account.status === 'active' ? 'Pausar' : 'Ativar'}</button><ConfirmButton question={`Excluir a conta ${account.label}?`} onConfirm={() => action.mutate({ account, operation: 'delete' })}>Excluir</ConfirmButton></>}</div></article>)}</div></section>)}</div>}{editing && <AccountForm platforms={platforms.data ?? []} account={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}{renewing && <CredentialRenewal {...renewing} onClose={() => setRenewing(null)} />}</div>
}
