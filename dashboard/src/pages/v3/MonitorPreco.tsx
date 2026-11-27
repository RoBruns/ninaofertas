import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PageHeader } from '../../components/v3/PageHeader'
import { Drawer } from '../../components/v3/Drawer'
import { Spinner } from '../../components/Spinner'
import { Field } from '../../components/Management'
import { useToast } from '../../components/useToast'
import { errorMessage } from '../../api/management'
import { v3api } from '../../v3/api'

type Monitor = {
  id: string
  url: string
  title: string | null
  image_url: string | null
  target_price: string
  last_price: string | null
  status: string
  last_checked_at: string | null
}

export function MonitorPreco() {
  const { showToast } = useToast()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [url, setUrl] = useState('')
  const [target, setTarget] = useState('100')
  const [title, setTitle] = useState('')
  const list = useQuery({
    queryKey: ['v3-monitors'],
    queryFn: () => v3api.get<Monitor[]>('/api/v3/monitors'),
  })
  const create = useMutation({
    mutationFn: () =>
      v3api.post('/api/v3/monitors', { url, target_price: target, title: title || null }),
    onSuccess: async () => {
      setOpen(false)
      setUrl('')
      setTitle('')
      await qc.invalidateQueries({ queryKey: ['v3-monitors'] })
      showToast('Monitor criado.', 'success')
    },
    onError: (e) => showToast(errorMessage(e), 'error'),
  })
  const check = useMutation({
    mutationFn: (id: string) => v3api.post<Monitor>(`/api/v3/monitors/${id}/check`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['v3-monitors'] })
      showToast('Checagem feita.', 'success')
    },
    onError: (e) => showToast(errorMessage(e), 'error'),
  })
  const remove = useMutation({
    mutationFn: (id: string) => v3api.delete(`/api/v3/monitors/${id}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['v3-monitors'] })
      showToast('Monitor removido.', 'success')
    },
    onError: (e) => showToast(errorMessage(e), 'error'),
  })
  if (list.isLoading) return <Spinner label="Carregando monitores" />
  return (
    <div>
      <PageHeader
        eyebrow="Radar"
        title="Monitor de preço"
        description="URL + alvo. Checagem MVP lê og:title/og:image e tenta achar R$ no HTML."
        actions={<button className="button primary" type="button" onClick={() => setOpen(true)}>Novo monitor</button>}
      />
      <div className="v3-grid">
        {(list.data ?? []).map((m) => {
          const last = m.last_price ? Number(m.last_price) : null
          const alvo = Number(m.target_price)
          const pct = last && alvo > 0 ? Math.min(100, Math.round((alvo / last) * 100)) : 0
          return (
            <article className="v3-card" key={m.id}>
              {m.image_url ? <img className="v3-card-media" src={m.image_url} alt="" /> : <div className="v3-card-media" />}
              <div className="v3-card-body">
                <span className="v3-chip">{m.status}</span>
                <h3>{m.title || m.url}</h3>
                <div className="v3-price">
                  alvo R$ {m.target_price}
                  {m.last_price ? <> · agora R$ {m.last_price}</> : null}
                </div>
                <div style={{ height: 6, background: 'var(--line)', borderRadius: 99 }}>
                  <div style={{ width: `${pct}%`, height: '100%', background: 'var(--primary)', borderRadius: 99 }} />
                </div>
                <div className="form-actions">
                  <button className="button ghost" type="button" disabled={check.isPending} onClick={() => check.mutate(m.id)}>
                    Checar
                  </button>
                  <button className="button ghost" type="button" onClick={() => remove.mutate(m.id)}>
                    Remover
                  </button>
                </div>
              </div>
            </article>
          )
        })}
      </div>
      {!list.data?.length && <p className="muted">Nenhum monitor.</p>}
      {open && (
        <Drawer title="Novo monitor" onClose={() => setOpen(false)}>
          <form
            className="form-grid"
            onSubmit={(e) => {
              e.preventDefault()
              create.mutate()
            }}
          >
            <Field label="URL"><input required value={url} onChange={(e) => setUrl(e.target.value)} /></Field>
            <Field label="Título (opcional)"><input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
            <Field label="Preço-alvo"><input required type="number" step="0.01" value={target} onChange={(e) => setTarget(e.target.value)} /></Field>
            <button className="button primary" disabled={create.isPending}>Salvar</button>
          </form>
        </Drawer>
      )}
    </div>
  )
}
