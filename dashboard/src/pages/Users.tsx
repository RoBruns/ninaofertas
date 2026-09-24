import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, apiFailure, ApiError } from '../api/client'
import { errorMessage, type UserResponse } from '../api/management'
import { useAuth } from '../auth/useAuth'
import { ConfirmButton, Field, Modal, StatusBadge } from '../components/Management'
import { Spinner } from '../components/Spinner'
import { useToast } from '../components/useToast'

function UserForm({ user, onClose }: { user?: UserResponse; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [email, setEmail] = useState(user?.email ?? '')
  const [name, setName] = useState(user?.name ?? '')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<'admin' | 'operator' | 'viewer'>(user?.role ?? 'viewer')
  const [fields, setFields] = useState<Readonly<Record<string, string>>>({})
  const save = useMutation({ mutationFn: async () => {
    const result = user
      ? await api.PATCH('/api/users/{user_id}', { params: { path: { user_id: user.id } }, body: { email, name: name || null, role, ...(password ? { password } : {}) } })
      : await api.POST('/api/users', { body: { email, name: name || null, password, role, is_active: true } })
    if (!result.data) throw apiFailure(result.error, result.response)
  }, onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['users'] }); showToast(user ? 'Usuário atualizado.' : 'Usuário criado.', 'success'); onClose() }, onError: (error) => { setFields(error instanceof ApiError ? error.fields : {}); showToast(errorMessage(error), 'error') } })
  return <Modal title={user ? 'Editar usuário' : 'Novo usuário'} onClose={onClose}><form className="form-grid" onSubmit={(event: FormEvent) => { event.preventDefault(); save.mutate() }}><Field label="Nome" error={fields.name}><input value={name} onChange={(event) => setName(event.target.value)} /></Field><Field label="E-mail" error={fields.email}><input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></Field><Field label={user ? 'Nova senha (opcional)' : 'Senha'} error={fields.password}><input required={!user} type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></Field><Field label="Papel" error={fields.role}><select value={role} onChange={(event) => setRole(event.target.value as typeof role)}><option value="viewer">Leitor</option><option value="operator">Operador</option><option value="admin">Administrador</option></select></Field><div className="form-actions"><button type="button" className="button ghost" onClick={onClose}>Cancelar</button><button className="button primary">Salvar</button></div></form></Modal>
}

export function Users() {
  const { user: currentUser } = useAuth()
  const queryClient = useQueryClient()
  const { showToast } = useToast()
  const [editing, setEditing] = useState<UserResponse | 'new' | null>(null)
  const users = useQuery({ queryKey: ['users'], queryFn: async () => { const result = await api.GET('/api/users', { params: { query: { page: 1, page_size: 100, sort: 'email' } } }); if (!result.data) throw apiFailure(result.error, result.response); return result.data.items }, enabled: currentUser?.role === 'admin' })
  const deactivate = useMutation({ mutationFn: async (user: UserResponse) => { const result = await api.DELETE('/api/users/{user_id}', { params: { path: { user_id: user.id } } }); if (result.response.status !== 204) throw apiFailure(result.error, result.response) }, onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['users'] }); showToast('Usuário desativado.', 'success') }, onError: (error) => showToast(errorMessage(error), 'error') })
  if (currentUser?.role !== 'admin') return <div className="page-error"><h2>Acesso restrito</h2><p>Somente administradores podem gerenciar usuários.</p></div>
  if (users.isLoading) return <Spinner label="Carregando usuários" />
  return <div><div className="page-heading"><div><p className="eyebrow">ACESSO</p><h1>Usuários</h1><p>Papéis e acesso ao dashboard.</p></div><button className="button primary" onClick={() => setEditing('new')}>Novo usuário</button></div>{users.isError && <div className="page-error">{errorMessage(users.error)}</div>}<div className="responsive-table"><table><thead><tr><th>Usuário</th><th>Papel</th><th>Status</th><th>Último acesso</th><th>Ações</th></tr></thead><tbody>{users.data?.map((user) => <tr key={user.id}><td data-label="Usuário"><strong>{user.name || user.email}</strong><small>{user.email}</small></td><td data-label="Papel"><StatusBadge value={user.role} /></td><td data-label="Status"><StatusBadge value={user.is_active ? 'active' : 'disabled'} /></td><td data-label="Último acesso">{user.last_login_at ? new Date(user.last_login_at).toLocaleString('pt-BR') : 'Nunca'}</td><td data-label="Ações"><div className="table-actions"><button className="button ghost" onClick={() => setEditing(user)}>Editar</button>{user.is_active && <ConfirmButton question={`Desativar ${user.email}?`} onConfirm={() => deactivate.mutate(user)}>Desativar</ConfirmButton>}</div></td></tr>)}</tbody></table></div>{editing && <UserForm user={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}</div>
}
