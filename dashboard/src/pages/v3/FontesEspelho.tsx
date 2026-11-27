import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, apiFailure } from '../../api/client'
import { errorMessage } from '../../api/management'
import { Field } from '../../components/Management'
import { PageHeader } from '../../components/v3/PageHeader'
import { Spinner } from '../../components/Spinner'
import { useToast } from '../../components/useToast'
import { useAuth } from '../../auth/useAuth'
import { v3api } from '../../v3/api'

type MirrorSources = {
  selected: string[]
  candidates: string[]
  max_selected: number
  source: string
  pending_skipped?: number
}

type FeedSource = {
  id: string
  slug: string
  name: string
  kind: string
  url: string
  enabled: boolean
  last_collected_at: string | null
  last_error: string | null
  total_collected: number
}

type SyncResult = {
  fontes: number
  lidas: number
  novas: number
  detalhes?: Array<{
    slug: string
    catalogadas?: number
    enfileiradas?: number
    aviso?: string
    erro?: string
  }>
}

function fmtWhen(iso: string | null) {
  if (!iso) return 'nunca'
  try {
    return new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
  } catch {
    return iso
  }
}

export function FontesEspelho() {
  const { user } = useAuth()
  const { showToast } = useToast()
  const qc = useQueryClient()
  const [rssName, setRssName] = useState('')
  const [rssUrl, setRssUrl] = useState('')

  const feeds = useQuery({
    queryKey: ['v3-sources'],
    queryFn: () => v3api.get<FeedSource[]>('/api/v3/sources'),
  })

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      v3api.patch<FeedSource>(`/api/v3/sources/${id}`, { enabled }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['v3-sources'] })
    },
    onError: (e) => showToast(errorMessage(e), 'error'),
  })

  const sync = useMutation({
    mutationFn: () => v3api.post<SyncResult>('/api/v3/sources/sync'),
    onSuccess: async (data) => {
      await qc.invalidateQueries({ queryKey: ['v3-sources'] })
      await qc.invalidateQueries({ queryKey: ['v3-esteira'] })
      await qc.invalidateQueries({ queryKey: ['v3-offers'] })
      await qc.invalidateQueries({ queryKey: ['v3-coupons'] })
      const aviso = data.detalhes?.map((d) => d.aviso || d.erro).filter(Boolean)[0]
      const cat = data.detalhes?.reduce((n, d) => n + (d.catalogadas || 0), 0) ?? 0
      showToast(
        data.novas
          ? `Esteira +${data.novas}. Catálogo +${cat}.`
          : aviso || `Lidas ${data.lidas}. Catálogo +${cat}. Esteira sem item enviável.`,
        data.novas ? 'success' : 'info',
      )
    },
    onError: (e) => showToast(errorMessage(e), 'error'),
  })

  const addRss = useMutation({
    mutationFn: () =>
      v3api.post<FeedSource>('/api/v3/sources', {
        name: rssName,
        url: rssUrl,
        kind: 'rss',
        enabled: true,
      }),
    onSuccess: async () => {
      setRssName('')
      setRssUrl('')
      await qc.invalidateQueries({ queryKey: ['v3-sources'] })
      showToast('RSS adicionado e ligado.', 'success')
    },
    onError: (e) => showToast(errorMessage(e), 'error'),
  })

  const mirror = useQuery({
    queryKey: ['platform-mirror-sources'],
    enabled: !!user?.is_platform_admin,
    queryFn: async () => {
      const result = await api.GET('/api/platform/mirror/source-groups')
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data as MirrorSources
    },
  })
  const [draft, setDraft] = useState<string[] | null>(null)
  const max = mirror.data?.max_selected ?? 3
  const selected = draft ?? mirror.data?.selected.slice(0, max) ?? []
  const saveMirror = useMutation({
    mutationFn: async () => {
      const result = await api.PUT('/api/platform/mirror/source-groups', {
        body: { names: selected, reset_to_default: false },
      })
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data as MirrorSources
    },
    onSuccess: async (data) => {
      setDraft(null)
      await qc.invalidateQueries({ queryKey: ['platform-mirror-sources'] })
      showToast(
        data.pending_skipped
          ? `Espelho salvo. ${data.pending_skipped} pendente(s) saíram.`
          : 'Origens do espelho salvas.',
        'success',
      )
    },
    onError: (e) => showToast(errorMessage(e), 'error'),
  })

  if (feeds.isLoading) return <Spinner label="Carregando fontes" />
  if (feeds.isError) return <div className="page-error">{errorMessage(feeds.error)}</div>

  return (
    <div>
      <PageHeader
        eyebrow="Fontes"
        title="Fontes & espelho"
        description="Coleta → aparece em Ofertas. Com bot ativo + telefone + link de loja, cai na Esteira e dispara sozinho."
        actions={
          <button
            className="button primary"
            type="button"
            disabled={sync.isPending}
            onClick={() => sync.mutate()}
          >
            {sync.isPending ? 'Sincronizando…' : 'Sincronizar agora'}
          </button>
        }
      />

      <section className="panel">
        <h2>Biblioteca BR</h2>
        <p className="muted">
          Ligar = coletor a cada ~45s. Oferta com link de loja vira pending na Esteira para cada bot ativo.
        </p>
        <div className="v3-grid">
          {(feeds.data ?? []).map((src) => (
            <article className="v3-card" key={src.id}>
              <div className="v3-card-body">
                <span className="v3-chip">{src.kind}</span>
                <h3>{src.name}</h3>
                <p className="muted" style={{ margin: 0, fontSize: '0.82rem', wordBreak: 'break-all' }}>
                  {src.url}
                </p>
                <small className="muted">
                  última: {fmtWhen(src.last_collected_at)} · {src.total_collected} na fila
                </small>
                {src.last_error ? (
                  <small style={{ color: 'var(--red-ink)' }}>{src.last_error}</small>
                ) : null}
                <label className="check">
                  <input
                    type="checkbox"
                    checked={src.enabled}
                    disabled={toggle.isPending}
                    onChange={(e) => toggle.mutate({ id: src.id, enabled: e.target.checked })}
                  />
                  {src.enabled ? 'Ligada' : 'Desligada'}
                </label>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>RSS customizado</h2>
        <div className="form-grid columns">
          <Field label="Nome">
            <input value={rssName} onChange={(e) => setRssName(e.target.value)} maxLength={80} />
          </Field>
          <Field label="URL do feed">
            <input value={rssUrl} onChange={(e) => setRssUrl(e.target.value)} placeholder="https://…" />
          </Field>
        </div>
        <div className="form-actions">
          <button
            className="button primary"
            type="button"
            disabled={addRss.isPending || rssName.trim().length < 2 || rssUrl.trim().length < 8}
            onClick={() => addRss.mutate()}
          >
            Adicionar RSS
          </button>
        </div>
      </section>

      {user?.is_platform_admin ? (
        <section className="panel">
          <h2>Espelho WhatsApp (Nina 1)</h2>
          <p className="muted">
            Até {max} grupos de origem. Menos origem = fila curta. Fonte: {mirror.data?.source ?? '—'}.
          </p>
          {mirror.isLoading ? (
            <Spinner label="Carregando origens" />
          ) : mirror.isError || !mirror.data ? (
            <div className="page-error">{errorMessage(mirror.error)}</div>
          ) : (
            <>
              <fieldset>
                <legend>Escolha até {max}</legend>
                <div className="selection-columns">
                  {mirror.data.candidates.map((name) => {
                    const checked = selected.includes(name)
                    const blocked = !checked && selected.length >= max
                    return (
                      <label className="check" key={name}>
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={blocked || saveMirror.isPending}
                          onChange={() =>
                            setDraft(
                              checked
                                ? selected.filter((n) => n !== name)
                                : selected.length >= max
                                  ? selected
                                  : [...selected, name],
                            )
                          }
                        />
                        {name}
                      </label>
                    )
                  })}
                </div>
              </fieldset>
              <p className="muted">
                {selected.length} / {max} selecionados.
              </p>
              <div className="form-actions">
                <button
                  className="button primary"
                  type="button"
                  disabled={saveMirror.isPending || selected.length < 1}
                  onClick={() => saveMirror.mutate()}
                >
                  Salvar origens do espelho
                </button>
              </div>
            </>
          )}
        </section>
      ) : (
        <p className="muted">Allowlist global do espelho: peça ao platform admin.</p>
      )}
    </div>
  )
}
