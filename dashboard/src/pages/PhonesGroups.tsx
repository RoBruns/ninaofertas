import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Pencil, Plus, QrCode, RefreshCw, Trash2 } from 'lucide-react'
import { api, apiFailure, ApiError } from '../api/client'
import { errorMessage, type Group, type Phone } from '../api/management'
import { useAuth } from '../auth/useAuth'
import { Field, Modal, StatusBadge } from '../components/Management'
import { Menu } from '../components/Menu'
import { EmptyState } from '../components/EmptyState'
import { Spinner } from '../components/Spinner'
import { useToast } from '../components/useToast'

function PhoneForm({ phone, onClose }: { phone?: Phone; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [label, setLabel] = useState(phone?.label ?? '')
  const [number, setNumber] = useState(phone?.number ?? '')
  const [instance, setInstance] = useState(phone?.evolution_instance ?? '')
  const [fields, setFields] = useState<Readonly<Record<string, string>>>({})
  const save = useMutation({ mutationFn: async () => {
    const result = phone ? await api.PATCH('/api/phones/{phone_id}', { params: { path: { phone_id: phone.id } }, body: { label, number, evolution_instance: instance || null } }) : await api.POST('/api/phones', { body: { label, number, evolution_instance: instance || null } })
    if (!result.data) throw apiFailure(result.error, result.response)
  }, onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['phones'] }); showToast(phone ? 'Telefone atualizado.' : 'Telefone cadastrado.', 'success'); onClose() }, onError: (error) => { setFields(error instanceof ApiError ? error.fields : {}); showToast(errorMessage(error), 'error') } })
  return <Modal title={phone ? 'Editar telefone' : 'Novo telefone'} onClose={onClose}><form className="form-grid" onSubmit={(event) => { event.preventDefault(); save.mutate() }}><Field label="Rótulo" error={fields.label}><input required value={label} onChange={(event) => setLabel(event.target.value)} /></Field><Field label="Número" error={fields.number}><input required value={number} onChange={(event) => setNumber(event.target.value)} /></Field><Field label="Instância Evolution" error={fields.evolution_instance}><input value={instance} onChange={(event) => setInstance(event.target.value)} /></Field><div className="form-actions"><button type="button" className="button ghost" onClick={onClose}>Cancelar</button><button className="button primary">Salvar</button></div></form></Modal>
}

function GroupForm({ phones, group, onClose }: { phones: Phone[]; group?: Group; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [phoneId, setPhoneId] = useState(group?.phone_id ?? phones[0]?.id ?? '')
  const [whatsappId, setWhatsappId] = useState(group?.whatsapp_id ?? '')
  const [name, setName] = useState(group?.name ?? '')
  const [participants, setParticipants] = useState(group?.participants?.toString() ?? '')
  const [isAnnounce, setIsAnnounce] = useState(group?.is_announce ?? false)
  const [botIsAdmin, setBotIsAdmin] = useState(group?.bot_is_admin ?? false)
  const [fields, setFields] = useState<Readonly<Record<string, string>>>({})
  const save = useMutation({ mutationFn: async () => {
    const base = { phone_id: phoneId, whatsapp_id: whatsappId, name: name || null, participants: participants ? Number(participants) : null, is_announce: isAnnounce, bot_is_admin: botIsAdmin }
    const result = group ? await api.PATCH('/api/groups/{group_id}', { params: { path: { group_id: group.id } }, body: base }) : await api.POST('/api/groups', { body: { ...base, status: 'active' } })
    if (!result.data) throw apiFailure(result.error, result.response)
  }, onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['groups'] }); showToast(group ? 'Grupo atualizado.' : 'Grupo cadastrado.', 'success'); onClose() }, onError: (error) => { setFields(error instanceof ApiError ? error.fields : {}); showToast(errorMessage(error), 'error') } })
  return <Modal title={group ? 'Editar grupo' : 'Cadastrar grupo manualmente'} onClose={onClose}><form className="form-grid" onSubmit={(event: FormEvent) => { event.preventDefault(); save.mutate() }}><Field label="Telefone" error={fields.phone_id}><select required value={phoneId} onChange={(event) => setPhoneId(event.target.value)}>{phones.map((phone) => <option key={phone.id} value={phone.id}>{phone.label}</option>)}</select></Field><Field label="ID do WhatsApp" error={fields.whatsapp_id}><input required value={whatsappId} onChange={(event) => setWhatsappId(event.target.value)} /></Field><Field label="Nome" error={fields.name}><input value={name} onChange={(event) => setName(event.target.value)} /></Field><Field label="Participantes" error={fields.participants}><input type="number" value={participants} onChange={(event) => setParticipants(event.target.value)} /></Field><label className="check"><input type="checkbox" checked={isAnnounce} onChange={(event) => setIsAnnounce(event.target.checked)} />Somente admins podem enviar</label><label className="check"><input type="checkbox" checked={botIsAdmin} onChange={(event) => setBotIsAdmin(event.target.checked)} />O bot é admin</label><div className="form-actions"><button type="button" className="button ghost" onClick={onClose}>Cancelar</button><button className="button primary">Salvar</button></div></form></Modal>
}

export function PhonesGroups() {
  const { user } = useAuth()
  const canEdit = user?.role === 'admin'
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const phones = useQuery({ queryKey: ['phones'], queryFn: async () => { const result = await api.GET('/api/phones', { params: { query: { page: 1, page_size: 100 } } }); if (!result.data) throw apiFailure(result.error, result.response); return result.data.items } })
  const groups = useQuery({ queryKey: ['groups'], queryFn: async () => { const result = await api.GET('/api/groups', { params: { query: { page: 1, page_size: 200 } } }); if (!result.data) throw apiFailure(result.error, result.response); return result.data.items } })
  const bots = useQuery({ queryKey: ['bots'], queryFn: async () => { const result = await api.GET('/api/bots', { params: { query: { page: 1, page_size: 200 } } }); if (!result.data) throw apiFailure(result.error, result.response); return result.data.items } })
  const [editingPhone, setEditingPhone] = useState<Phone | 'new' | null>(null)
  const [editingGroup, setEditingGroup] = useState<Group | 'new' | null>(null)
  const [qr, setQr] = useState<{ label: string; source: string; expires: string } | null>(null)
  const phoneAction = useMutation({ mutationFn: async ({ phone, operation }: { phone: Phone; operation: 'sync' | 'qr' | 'delete' }) => {
    if (operation === 'sync') {
      const result = await api.POST('/api/phones/{phone_id}/sync-groups', { params: { path: { phone_id: phone.id } } })
      if (!result.data) throw apiFailure(result.error, result.response)
      return { operation, phone, data: '' }
    }
    if (operation === 'qr') {
      const result = await api.GET('/api/phones/{phone_id}/qrcode', { params: { path: { phone_id: phone.id } } })
      if (!result.data) throw apiFailure(result.error, result.response)
      return { operation, phone, data: result.data }
    }
    const result = await api.DELETE('/api/phones/{phone_id}', { params: { path: { phone_id: phone.id } } })
    if (result.response.status !== 204) throw apiFailure(result.error, result.response)
    return { operation, phone, data: '' }
  }, onSuccess: async (result) => {
    if (result.operation === 'sync') showToast('Sincronização pedida; os grupos aparecem em alguns minutos.', 'success')
    if (result.operation === 'qr' && typeof result.data === 'object') setQr({ label: result.phone.label, source: result.data.qrcode_base64.startsWith('data:') ? result.data.qrcode_base64 : `data:image/png;base64,${result.data.qrcode_base64}`, expires: result.data.expires_at })
    await Promise.all([queryClient.invalidateQueries({ queryKey: ['phones'] }), queryClient.invalidateQueries({ queryKey: ['groups'] })])
  }, onError: (error) => showToast(errorMessage(error), 'error') })
  if (phones.isLoading || groups.isLoading) return <Spinner label="Carregando telefones e grupos" />
  return <div><div className="page-heading"><div><h1>Telefones e grupos</h1><p>Conexões, grupos descobertos e entrega de mensagens.</p></div>{canEdit && <div className="page-actions"><button className="button ghost" onClick={() => setEditingGroup('new')}>Cadastrar grupo</button><button className="button primary" onClick={() => setEditingPhone('new')}><Plus />Novo telefone</button></div>}</div><section className="panel"><h2>Telefones</h2>{!phones.data?.length ? <EmptyState title="Nenhum telefone" description="Cadastre uma conexão do WhatsApp." /> : <div className="card-list">{phones.data.map((phone) => { const usedBy = (bots.data ?? []).filter((bot) => bot.phone_id === phone.id); return <article className="management-card" key={phone.id}><div className="card-title"><div><h3>{phone.label}</h3><small>{phone.number}</small></div><div className="card-title-actions"><StatusBadge value={phone.status} />{canEdit && <Menu label={`Mais ações de ${phone.label}`} items={[{ label: 'Editar', icon: <Pencil />, onClick: () => setEditingPhone(phone) }, { label: 'Excluir', icon: <Trash2 />, danger: true, confirm: `Excluir o telefone ${phone.label}?`, actionLabel: 'Excluir', onClick: () => phoneAction.mutate({ phone, operation: 'delete' }) }]} />}</div></div><p><strong>Bots que usam este telefone:</strong> {usedBy.length ? usedBy.map((bot) => bot.name).join(', ') : 'nenhum'}</p><div className="card-actions"><button className="button ghost" onClick={() => phoneAction.mutate({ phone, operation: 'qr' })}><QrCode />Ver QR code</button>{user?.role !== 'viewer' && <button className="button ghost" onClick={() => phoneAction.mutate({ phone, operation: 'sync' })}><RefreshCw />Sincronizar grupos</button>}</div></article> })}</div>}</section><section className="panel"><h2>Grupos</h2>{!groups.data?.length ? <EmptyState title="Nenhum grupo" description="Sincronize um telefone ou cadastre um grupo manualmente." /> : <div className="responsive-table"><table><thead><tr><th>Grupo</th><th>Telefone</th><th>Status</th><th>Participantes</th><th>Usado por</th><th>Aviso</th><th>Ações</th></tr></thead><tbody>{groups.data.map((group) => { const usedBy = (bots.data ?? []).filter((bot) => bot.group_ids.includes(group.id)); return <tr className={group.warning ? 'warning-row' : ''} key={group.id}><td data-label="Grupo"><strong>{group.name ?? 'Sem nome'}</strong><small>{group.whatsapp_id}</small></td><td data-label="Telefone">{phones.data?.find((phone) => phone.id === group.phone_id)?.label ?? '—'}</td><td data-label="Status"><StatusBadge value={group.status} /></td><td data-label="Participantes">{group.participants ?? '—'}</td><td data-label="Usado por">{usedBy.length ? usedBy.map((bot) => bot.name).join(', ') : 'Nenhum bot'}</td><td data-label="Aviso">{group.warning ? <div className="group-warning" role="alert">⚠ {group.warning}</div> : '—'}</td><td data-label="Ações">{canEdit && <button className="button ghost" onClick={() => setEditingGroup(group)}>Editar</button>}</td></tr> })}</tbody></table></div>}</section>{editingPhone && <PhoneForm phone={editingPhone === 'new' ? undefined : editingPhone} onClose={() => setEditingPhone(null)} />}{editingGroup && <GroupForm phones={phones.data ?? []} group={editingGroup === 'new' ? undefined : editingGroup} onClose={() => setEditingGroup(null)} />}{qr && <Modal title={`QR code — ${qr.label}`} onClose={() => setQr(null)}><div className="qr-modal"><img src={qr.source} alt={`QR code de ${qr.label}`} /><p>Expira em {new Date(qr.expires).toLocaleString('pt-BR')}</p></div></Modal>}</div>
}
