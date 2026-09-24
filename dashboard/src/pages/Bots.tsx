import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Copy, ExternalLink, Pause, Play, Plus, Power, Trash2 } from 'lucide-react'
import { api, apiFailure, ApiError } from '../api/client'
import { defaultSettings, errorMessage, type Bot, type BotCreate, type Niche, type Phone } from '../api/management'
import { useAuth } from '../auth/useAuth'
import { Field, Modal, StatusBadge } from '../components/Management'
import { Menu } from '../components/Menu'
import { EmptyState } from '../components/EmptyState'
import { Spinner } from '../components/Spinner'
import { useToast } from '../components/useToast'
import { healthText } from '../lib/format'

async function loadBots() {
  const result = await api.GET('/api/bots', { params: { query: { page: 1, page_size: 100, sort: 'name' } } })
  if (!result.data) throw apiFailure(result.error, result.response)
  return result.data.items
}

async function loadNiches() {
  const result = await api.GET('/api/niches')
  if (!result.data) throw apiFailure(result.error, result.response)
  return result.data
}

async function loadPhones() {
  const result = await api.GET('/api/phones', { params: { query: { page: 1, page_size: 100 } } })
  if (!result.data) throw apiFailure(result.error, result.response)
  return result.data.items
}

function BotHealth({ botId }: { botId: string }) {
  const health = useQuery({ queryKey: ['bot-health', botId], queryFn: async () => {
    const result = await api.GET('/api/bots/{bot_id}/health', { params: { path: { bot_id: botId } } })
    if (!result.data) throw apiFailure(result.error, result.response)
    return result.data
  }, refetchInterval: 30_000 })
  if (!health.data) return <span className="health health-unknown">{healthText(undefined, undefined)}</span>
  return <span className={`health health-${health.data.status || 'unknown'}`}>{healthText(health.data.status, health.data.message)}</span>
}

function CreateBot({ niches, phones, onClose }: { niches: Niche[]; phones: Phone[]; onClose: () => void }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [nicheId, setNicheId] = useState('')
  const [phoneId, setPhoneId] = useState('')
  const [fields, setFields] = useState<Readonly<Record<string, string>>>({})
  const create = useMutation({ mutationFn: async () => {
    const body: BotCreate = { name, slug, niche_id: nicheId ? Number(nicheId) : null, phone_id: phoneId || null, settings: defaultSettings }
    const result = await api.POST('/api/bots', { body })
    if (!result.data) throw apiFailure(result.error, result.response)
    return result.data
  }, onSuccess: async (bot) => { await queryClient.invalidateQueries({ queryKey: ['bots'] }); showToast('Bot criado pausado.', 'success'); navigate(`/bots/${bot.id}`) }, onError: (error) => { setFields(error instanceof ApiError ? error.fields : {}); showToast(errorMessage(error), 'error') } })
  const submit = (event: FormEvent) => { event.preventDefault(); create.mutate() }
  return <Modal title="Novo bot" onClose={onClose}><form className="form-grid" onSubmit={submit}><Field label="Nome" error={fields.name}><input required value={name} onChange={(event) => { setName(event.target.value); if (!slug) setSlug(event.target.value.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')) }} /></Field><Field label="Slug" error={fields.slug}><input required value={slug} onChange={(event) => setSlug(event.target.value)} /></Field><Field label="Nicho" error={fields.niche_id}><select value={nicheId} onChange={(event) => setNicheId(event.target.value)}><option value="">Sem nicho</option>{niches.map((niche) => <option key={niche.id} value={niche.id}>{niche.name}</option>)}</select></Field><Field label="Telefone" error={fields.phone_id}><select value={phoneId} onChange={(event) => setPhoneId(event.target.value)}><option value="">Sem telefone</option>{phones.map((phone) => <option key={phone.id} value={phone.id}>{phone.label} · {phone.number}</option>)}</select></Field><div className="form-actions"><button type="button" className="button ghost" onClick={onClose}>Cancelar</button><button className="button primary" disabled={create.isPending}>Criar bot</button></div></form></Modal>
}

export function Bots() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const bots = useQuery({ queryKey: ['bots'], queryFn: loadBots })
  const niches = useQuery({ queryKey: ['niches'], queryFn: loadNiches })
  const phones = useQuery({ queryKey: ['phones'], queryFn: loadPhones })
  const [creating, setCreating] = useState(false)
  const canOperate = user?.role !== 'viewer'
  const isAdmin = user?.role === 'admin'
  const act = useMutation({ mutationFn: async ({ bot, operation }: { bot: Bot; operation: 'activate' | 'pause' | 'disable' | 'run' | 'duplicate' | 'delete' }) => {
    if (operation === 'delete') {
      const result = await api.DELETE('/api/bots/{bot_id}', { params: { path: { bot_id: bot.id } } })
      if (result.response.status !== 204) throw apiFailure(result.error, result.response)
      return null
    }
    const result = operation === 'activate' ? await api.POST('/api/bots/{bot_id}/activate', { params: { path: { bot_id: bot.id } } })
      : operation === 'pause' ? await api.POST('/api/bots/{bot_id}/pause', { params: { path: { bot_id: bot.id } } })
        : operation === 'disable' ? await api.POST('/api/bots/{bot_id}/disable', { params: { path: { bot_id: bot.id } } })
          : operation === 'run' ? await api.POST('/api/bots/{bot_id}/run-now', { params: { path: { bot_id: bot.id } } })
            : await api.POST('/api/bots/{bot_id}/duplicate', { params: { path: { bot_id: bot.id } } })
    if (!result.data) throw apiFailure(result.error, result.response)
    return operation === 'duplicate' ? result.data : null
  }, onSuccess: async (copy, variables) => {
    await queryClient.invalidateQueries({ queryKey: ['bots'] })
    showToast(variables.operation === 'run' ? 'Execução solicitada.' : variables.operation === 'duplicate' ? 'Cópia criada pausada.' : 'Bot atualizado.', 'success')
    if (variables.operation === 'duplicate' && copy && 'id' in copy) navigate(`/bots/${copy.id}`)
  }, onError: (error) => showToast(errorMessage(error), 'error') })
  if (bots.isLoading) return <Spinner label="Carregando bots" />
  return <div><div className="page-heading"><div><h1>Bots</h1><p>Operação, saúde e ritmo de publicação.</p></div>{isAdmin && <button className="button primary" onClick={() => setCreating(true)}><Plus />Novo bot</button>}</div>{bots.isError && <div className="page-error">{errorMessage(bots.error)}</div>}{!bots.data?.length ? <EmptyState title="Nenhum bot" description="Crie o primeiro bot para começar." /> : <div className="responsive-table"><table><thead><tr><th>Bot</th><th>Status</th><th>Nicho</th><th>Telefone</th><th>Grupos</th><th>Saúde</th><th>Ações</th></tr></thead><tbody>{bots.data.map((bot) => <tr key={bot.id}><td data-label="Bot"><Link to={`/bots/${bot.id}`}><strong>{bot.name}</strong></Link><small>{bot.slug}</small></td><td data-label="Status"><StatusBadge value={bot.status} /></td><td data-label="Nicho">{niches.data?.find((niche) => niche.id === bot.niche_id)?.name ?? '—'}</td><td data-label="Telefone">{phones.data?.find((phone) => phone.id === bot.phone_id)?.label ?? '—'}</td><td data-label="Grupos">{bot.group_ids.length}</td><td data-label="Saúde"><BotHealth botId={bot.id} /></td><td data-label="Ações"><div className="table-actions">{canOperate && <button className="button ghost" onClick={() => act.mutate({ bot, operation: bot.status === 'active' ? 'pause' : 'activate' })}>{bot.status === 'active' ? <Pause /> : <Play />}{bot.status === 'active' ? 'Pausar' : 'Ativar'}</button>}<Menu label={`Mais ações de ${bot.name}`} items={[{ label: 'Abrir', icon: <ExternalLink />, href: `/bots/${bot.id}` }, ...(canOperate ? [{ label: 'Rodar agora', icon: <Play />, onClick: () => act.mutate({ bot, operation: 'run' as const }) }] : []), ...(isAdmin ? [{ label: 'Duplicar', icon: <Copy />, onClick: () => act.mutate({ bot, operation: 'duplicate' as const }) }, { separator: true }, { label: 'Desativar', icon: <Power />, confirm: `Desativar ${bot.name}?`, actionLabel: 'Desativar', onClick: () => act.mutate({ bot, operation: 'disable' as const }) }, { label: 'Excluir', icon: <Trash2 />, danger: true, confirm: `Excluir definitivamente ${bot.name}?`, consequence: 'Esta ação não pode ser desfeita.', actionLabel: 'Excluir', onClick: () => act.mutate({ bot, operation: 'delete' as const }) }] : [])]} /></div></td></tr>)}</tbody></table></div>}{creating && <CreateBot niches={niches.data ?? []} phones={phones.data ?? []} onClose={() => setCreating(false)} />}</div>
}
