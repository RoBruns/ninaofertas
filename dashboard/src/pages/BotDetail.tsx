import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Copy, Pause, Play, Power } from 'lucide-react'
import type { components } from '../api/schema'
import { api, apiFailure, ApiError } from '../api/client'
import { defaultSettings, errorMessage, type Account, type BotSettings, type Group, type Niche, type Phone } from '../api/management'
import { useAuth } from '../auth/useAuth'
import { Field, StatusBadge, TagsInput } from '../components/Management'
import { Menu } from '../components/Menu'
import { Spinner } from '../components/Spinner'
import { useToast } from '../components/useToast'
import { healthText } from '../lib/format'
import { renderMessagePreview } from '../lib/messagePreview'
import { WhatsAppText } from '../components/WhatsAppText'

type Pacing = components['schemas']['Pacing']
type Filters = components['schemas']['Filters']
const pacingFields: ReadonlyArray<readonly [keyof Pacing, string]> = [
  ['max_ofertas_por_ciclo', 'Máximo por ciclo'],
  ['intervalo_minutos_entre_ofertas', 'Intervalo entre ofertas (min)'],
  ['max_ofertas_por_rajada', 'Máximo por rajada'],
  ['janela_rajada_minutos', 'Janela da rajada (min)'],
  ['pausa_entre_rajadas_minutos', 'Pausa entre rajadas (min)'],
  ['max_ofertas_por_hora', 'Máximo por hora'],
  ['max_ofertas_por_dia', 'Máximo por dia'],
  ['max_ofertas_globais_por_hora', 'Máximo global por hora'],
  ['max_ofertas_globais_por_dia', 'Máximo global por dia'],
]
const tagFields: ReadonlyArray<readonly [keyof Filters, string]> = [
  ['lojas', 'Lojas'], ['categorias_meli', 'Categorias Mercado Livre'],
  ['termos_busca', 'Termos de busca'], ['palavras_chave', 'Palavras-chave'],
  ['bloquear_produtos', 'Bloquear produtos'], ['bloquear_termos', 'Bloquear termos'],
  ['excecoes_bloqueio', 'Exceções de bloqueio'],
]

function editableSettings(source: components['schemas']['BotSettings']): BotSettings {
  return {
    ...source,
    schema_version: 1,
    filters: { ...defaultSettings.filters, ...source.filters },
    pacing: { ...defaultSettings.pacing, ...source.pacing },
    content: { ...defaultSettings.content, ...source.content },
    schedule: { ...defaultSettings.schedule, ...source.schedule, quiet_hours: { ...defaultSettings.schedule?.quiet_hours, ...source.schedule?.quiet_hours } },
  }
}

async function loadBot(id: string) {
  const result = await api.GET('/api/bots/{bot_id}', { params: { path: { bot_id: id } } })
  if (!result.data) throw apiFailure(result.error, result.response)
  return result.data
}

export function BotDetail() {
  const { id = '' } = useParams()
  const { user } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const bot = useQuery({ queryKey: ['bot', id], queryFn: () => loadBot(id), enabled: Boolean(id) })
  const niches = useQuery({ queryKey: ['niches'], queryFn: async () => { const result = await api.GET('/api/niches'); if (!result.data) throw apiFailure(result.error, result.response); return result.data } })
  const phones = useQuery({ queryKey: ['phones'], queryFn: async () => { const result = await api.GET('/api/phones', { params: { query: { page: 1, page_size: 100 } } }); if (!result.data) throw apiFailure(result.error, result.response); return result.data.items } })
  const groups = useQuery({ queryKey: ['groups'], queryFn: async () => { const result = await api.GET('/api/groups', { params: { query: { page: 1, page_size: 200 } } }); if (!result.data) throw apiFailure(result.error, result.response); return result.data.items } })
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: async () => { const result = await api.GET('/api/accounts', { params: { query: { page: 1, page_size: 200 } } }); if (!result.data) throw apiFailure(result.error, result.response); return result.data.items } })
  const runs = useQuery({ queryKey: ['bot-runs', id], queryFn: async () => { const result = await api.GET('/api/bots/{bot_id}/runs', { params: { path: { bot_id: id }, query: { page: 1, page_size: 25 } } }); if (!result.data) throw apiFailure(result.error, result.response); return result.data.items }, refetchInterval: 30_000 })
  const health = useQuery({ queryKey: ['bot-health', id], queryFn: async () => { const result = await api.GET('/api/bots/{bot_id}/health', { params: { path: { bot_id: id } } }); if (!result.data) throw apiFailure(result.error, result.response); return result.data }, refetchInterval: 30_000 })
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [nicheId, setNicheId] = useState('')
  const [phoneId, setPhoneId] = useState('')
  const [messageTemplate, setMessageTemplate] = useState('')
  const [settings, setSettings] = useState<BotSettings>(defaultSettings)
  const [groupIds, setGroupIds] = useState<string[]>([])
  const [accountIds, setAccountIds] = useState<string[]>([])
  const [fields, setFields] = useState<Readonly<Record<string, string>>>({})
  const [pacingError, setPacingError] = useState('')
  // Query data is copied into an editable draft only when a fresh server version arrives.
  // oxlint-disable react/set-state-in-effect
  useEffect(() => {
    if (!bot.data) return
    setName(bot.data.name); setSlug(bot.data.slug); setNicheId(bot.data.niche_id?.toString() ?? '')
    setPhoneId(bot.data.phone_id ?? ''); setMessageTemplate(bot.data.message_template ?? '')
    setSettings(editableSettings(bot.data.settings)); setGroupIds(bot.data.group_ids); setAccountIds(bot.data.account_ids)
  }, [bot.data])
  // oxlint-enable react/set-state-in-effect
  const invalidate = async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: ['bot', id] }), queryClient.invalidateQueries({ queryKey: ['bots'] }), queryClient.invalidateQueries({ queryKey: ['bot-health', id] })]) }
  const save = useMutation({ mutationFn: async () => {
    const result = await api.PATCH('/api/bots/{bot_id}', { params: { path: { bot_id: id } }, body: { name, slug, niche_id: nicheId ? Number(nicheId) : null, phone_id: phoneId || null, message_template: messageTemplate || null, settings } })
    if (!result.data) throw apiFailure(result.error, result.response)
    const groupResult = await api.PUT('/api/bots/{bot_id}/groups', { params: { path: { bot_id: id } }, body: { group_ids: groupIds } })
    if (!groupResult.data) throw apiFailure(groupResult.error, groupResult.response)
    const accountResult = await api.PUT('/api/bots/{bot_id}/accounts', { params: { path: { bot_id: id } }, body: { account_ids: accountIds } })
    if (!accountResult.data) throw apiFailure(accountResult.error, accountResult.response)
  }, onSuccess: async () => { setFields({}); setPacingError(''); await invalidate(); showToast('Bot salvo.', 'success') }, onError: (error) => {
    const apiError = error instanceof ApiError ? error : null
    setFields(apiError?.fields ?? {})
    if (apiError?.status === 422 && (apiError.message.toLowerCase().includes('ban') || Object.keys(apiError.fields).some((key) => key.includes('pacing')))) setPacingError(apiError.message)
    showToast(errorMessage(error), 'error')
  } })
  const act = useMutation({ mutationFn: async (operation: 'activate' | 'pause' | 'disable' | 'run' | 'duplicate') => {
    const result = operation === 'activate' ? await api.POST('/api/bots/{bot_id}/activate', { params: { path: { bot_id: id } } })
      : operation === 'pause' ? await api.POST('/api/bots/{bot_id}/pause', { params: { path: { bot_id: id } } })
        : operation === 'disable' ? await api.POST('/api/bots/{bot_id}/disable', { params: { path: { bot_id: id } } })
          : operation === 'run' ? await api.POST('/api/bots/{bot_id}/run-now', { params: { path: { bot_id: id } } })
            : await api.POST('/api/bots/{bot_id}/duplicate', { params: { path: { bot_id: id } } })
    if (!result.data) throw apiFailure(result.error, result.response)
    return operation === 'duplicate' ? result.data : null
  }, onSuccess: async (copy, operation) => { await invalidate(); showToast(operation === 'run' ? 'Execução solicitada.' : 'Bot atualizado.', 'success'); if (operation === 'duplicate' && copy && 'id' in copy) navigate(`/bots/${copy.id}`) }, onError: (error) => showToast(errorMessage(error), 'error') })
  const updateFilter = <K extends keyof Filters>(key: K, value: Filters[K]) => setSettings((current) => ({ ...current, filters: { ...current.filters, [key]: value } }))
  const canOperate = user?.role !== 'viewer'
  const isAdmin = user?.role === 'admin'
  if (bot.isLoading) return <Spinner label="Carregando bot" />
  if (!bot.data) return <div className="page-error"><h2>Bot não encontrado</h2><Link to="/bots">Voltar</Link></div>
  const filters = settings.filters ?? defaultSettings.filters!
  const pacing = settings.pacing ?? defaultSettings.pacing!
  const content = settings.content ?? defaultSettings.content!
  const schedule = settings.schedule ?? defaultSettings.schedule!
  const submit = (event: FormEvent) => { event.preventDefault(); setPacingError(''); save.mutate() }
  return <div><div className="page-heading"><div><Link to="/bots"><ArrowLeft /> Bots</Link><h1>{bot.data.name}</h1><p><StatusBadge value={bot.data.status} /> {health.data && <span className={`health health-${health.data.status || 'unknown'}`}>{healthText(health.data.status, health.data.message)}</span>}</p></div><div className="page-actions">{canOperate && <><button className="button ghost" onClick={() => act.mutate(bot.data.status === 'active' ? 'pause' : 'activate')}>{bot.data.status === 'active' ? <Pause /> : <Play />}{bot.data.status === 'active' ? 'Pausar' : 'Ativar'}</button><button className="button primary" onClick={() => act.mutate('run')}><Play />Rodar agora</button></>}{isAdmin && <Menu label={`Mais ações de ${bot.data.name}`} items={[{ label: 'Duplicar', icon: <Copy />, onClick: () => act.mutate('duplicate') }, { label: 'Desativar', icon: <Power />, confirm: `Desativar ${bot.data.name}?`, actionLabel: 'Desativar', onClick: () => act.mutate('disable') }]} />}</div></div><form onSubmit={submit} className="bot-editor"><section className="panel"><h2>Identificação</h2><p>Nome, nicho, telefone e mensagem usados por este bot.</p><div className="form-grid columns"><Field label="Nome" error={fields.name}><input disabled={!isAdmin} value={name} onChange={(event) => setName(event.target.value)} /></Field><Field label="Slug" error={fields.slug}><input disabled={!isAdmin} value={slug} onChange={(event) => setSlug(event.target.value)} /></Field><Field label="Nicho" error={fields.niche_id}><select disabled={!isAdmin} value={nicheId} onChange={(event) => setNicheId(event.target.value)}><option value="">Sem nicho</option>{(niches.data ?? []).map((niche: Niche) => <option value={niche.id} key={niche.id}>{niche.name}</option>)}</select></Field><Field label="Telefone" error={fields.phone_id}><select disabled={!isAdmin} value={phoneId} onChange={(event) => setPhoneId(event.target.value)}><option value="">Sem telefone</option>{(phones.data ?? []).map((phone: Phone) => <option value={phone.id} key={phone.id}>{phone.label} · {phone.number}</option>)}</select></Field><Field label="Template da mensagem" className="wide" error={fields.message_template}><textarea disabled={!isAdmin} value={messageTemplate} onChange={(event) => setMessageTemplate(event.target.value)} /><small>Variáveis: {'{nome}'} {'{de_por}'} (De ~R$ antigo~ por *R$ novo*) {'{preco}'} {'{cupom}'} {'{loja}'} {'{url}'} {'{hora}'}. A linha cuja variável fica vazia (sem cupom, sem preço) some. *texto* = negrito e ~texto~ = riscado no WhatsApp. Com {'{preco_anterior}'} e {'{desconto}'} vale o modelo completo antigo. Vazio = modelo padrão.</small><div className="message-preview" aria-label="Prévia da mensagem"><WhatsAppText text={renderMessagePreview(messageTemplate)} /></div></Field></div></section><section className="panel"><h2>Filtros</h2><p>Critérios que definem quais ofertas entram na seleção.</p><div className="form-grid columns"><Field label="Preço mínimo"><input disabled={!isAdmin} type="number" value={filters.preco_minimo} onChange={(event) => updateFilter('preco_minimo', Number(event.target.value))} /></Field><Field label="Preço máximo"><input disabled={!isAdmin} type="number" value={filters.preco_maximo} onChange={(event) => updateFilter('preco_maximo', Number(event.target.value))} /></Field><Field label="Desconto mínimo (%)"><input disabled={!isAdmin} type="number" value={filters.desconto_minimo} onChange={(event) => updateFilter('desconto_minimo', Number(event.target.value))} /></Field><Field label="Máximo de vendas"><input disabled={!isAdmin} type="number" value={filters.max_vendas} onChange={(event) => updateFilter('max_vendas', Number(event.target.value))} /></Field><Field label="Idade máxima da oferta (h)"><input disabled={!isAdmin} type="number" value={filters.max_idade_oferta_horas} onChange={(event) => updateFilter('max_idade_oferta_horas', Number(event.target.value))} /></Field></div>{tagFields.map(([key, label]) => <TagsInput key={key} label={label} value={Array.isArray(filters[key]) ? filters[key] as string[] : []} onChange={(value) => updateFilter(key, value)} />)}</section><section className={`panel pacing-panel ${pacingError ? 'has-error' : ''}`}><h2>Ritmo</h2><p className="muted">A API verifica os limites seguros para proteger o número contra banimento.</p>{pacingError && <div className="pacing-error" role="alert"><strong>Risco para o número</strong><span>{pacingError}</span></div>}<div className="form-grid columns">{pacingFields.map(([key, label]) => <Field key={key} label={label} error={fields[`settings.pacing.${key}`] ?? fields[`pacing.${key}`] ?? fields[key]}><input disabled={!isAdmin} type="number" value={pacing[key]} onChange={(event) => setSettings((current) => ({ ...current, pacing: { ...pacing, [key]: Number(event.target.value) } }))} /></Field>)}</div></section><section className="panel"><h2>Conteúdo</h2><p>Tipos e limites do conteúdo enviado aos grupos.</p><div className="form-grid columns"><Field label="Máximo de cupons por dia"><input disabled={!isAdmin} type="number" value={content.max_cupons_por_dia} onChange={(event) => setSettings((current) => ({ ...current, content: { ...content, max_cupons_por_dia: Number(event.target.value) } }))} /></Field><Field label="Ciclos de baseline"><input disabled={!isAdmin} type="number" value={content.baseline_ciclos} onChange={(event) => setSettings((current) => ({ ...current, content: { ...content, baseline_ciclos: Number(event.target.value) } }))} /></Field><label className="check"><input disabled={!isAdmin} type="checkbox" checked={content.aceitar_cupons} onChange={(event) => setSettings((current) => ({ ...current, content: { ...content, aceitar_cupons: event.target.checked } }))} />Aceitar cupons</label><label className="check"><input disabled={!isAdmin} type="checkbox" checked={content.aceitar_campanhas} onChange={(event) => setSettings((current) => ({ ...current, content: { ...content, aceitar_campanhas: event.target.checked } }))} />Aceitar campanhas</label></div></section><section className="panel"><h2>Agenda</h2><p>Horário de silêncio (Brasília) — nenhuma oferta nem recado entre o início e o fim. Início = fim desliga o silêncio.</p><div className="form-grid columns"><Field label="Intervalo de verificação (s)"><input disabled={!isAdmin} type="number" value={schedule.check_interval} onChange={(event) => setSettings((current) => ({ ...current, schedule: { ...schedule, check_interval: Number(event.target.value) } }))} /></Field><Field label="Silêncio começa"><input disabled={!isAdmin} type="time" value={schedule.quiet_hours?.start ?? ''} onChange={(event) => setSettings((current) => ({ ...current, schedule: { ...schedule, quiet_hours: { start: event.target.value, end: schedule.quiet_hours?.end ?? '08:00' } } }))} /></Field><Field label="Silêncio termina"><input disabled={!isAdmin} type="time" value={schedule.quiet_hours?.end ?? ''} onChange={(event) => setSettings((current) => ({ ...current, schedule: { ...schedule, quiet_hours: { start: schedule.quiet_hours?.start ?? '00:00', end: event.target.value } } }))} /></Field></div></section><section className="panel"><h2>Grupos e contas</h2><p>Destinos de publicação e contas usadas pelo bot.</p><div className="selection-columns"><fieldset><legend>Grupos</legend>{(groups.data ?? []).map((group: Group) => <label className="check" key={group.id}><input disabled={!isAdmin} type="checkbox" checked={groupIds.includes(group.id)} onChange={(event) => setGroupIds(event.target.checked ? [...groupIds, group.id] : groupIds.filter((value) => value !== group.id))} />{group.name ?? group.whatsapp_id}{group.warning && <small className="field-error">{group.warning}</small>}</label>)}</fieldset><fieldset><legend>Contas</legend>{(accounts.data ?? []).map((account: Account) => <label className="check" key={account.id}><input disabled={!isAdmin} type="checkbox" checked={accountIds.includes(account.id)} onChange={(event) => setAccountIds(event.target.checked ? [...accountIds, account.id] : accountIds.filter((value) => value !== account.id))} />{account.label} · {account.platform.name}</label>)}</fieldset></div></section>{isAdmin && <div className="sticky-save"><button className="button primary" disabled={save.isPending}>Salvar alterações</button></div>}</form><section className="panel runs-panel"><h2>Histórico de execuções</h2>{!runs.data?.length ? <p className="muted">Nenhuma execução registrada.</p> : <div className="responsive-table"><table><thead><tr><th>Início</th><th>Tipo</th><th>Status</th><th>Encontradas</th><th>Enviadas</th><th>Erro</th></tr></thead><tbody>{runs.data.map((run) => <tr key={run.id}><td data-label="Início">{new Date(run.started_at).toLocaleString('pt-BR')}</td><td data-label="Tipo">{run.kind}</td><td data-label="Status"><StatusBadge value={run.status} /></td><td data-label="Encontradas">{run.offers_found ?? '—'}</td><td data-label="Enviadas">{run.offers_sent ?? '—'}</td><td data-label="Erro">{run.error ?? '—'}</td></tr>)}</tbody></table></div>}</section></div>
}
