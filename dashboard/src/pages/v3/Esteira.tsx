import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PageHeader } from '../../components/v3/PageHeader'
import { Spinner } from '../../components/Spinner'
import { useToast } from '../../components/useToast'
import { errorMessage } from '../../api/management'
import { v3api } from '../../v3/api'

type InboxItem = {
  id: string
  bot_id: string
  source_group_name: string | null
  body_text: string
  status: string
  skip_reason: string | null
  created_at: string
}

type Page = { items: InboxItem[]; total: number; page: number; page_size: number }

export function Esteira() {
  const { showToast } = useToast()
  const qc = useQueryClient()
  const inbox = useQuery({
    queryKey: ['v3-esteira'],
    queryFn: () => v3api.get<Page>('/api/v3/mirror-inbox?page_size=80'),
    refetchInterval: 10_000,
  })
  const skip = useMutation({
    mutationFn: (id: string) =>
      v3api.patch(`/api/v3/mirror-inbox/${id}`, { status: 'skipped', skip_reason: 'manual' }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['v3-esteira'] })
      showToast('Item removido da fila.', 'success')
    },
    onError: (e) => showToast(errorMessage(e), 'error'),
  })
  if (inbox.isLoading) return <Spinner label="Carregando esteira" />
  if (inbox.isError) return <div className="page-error">{errorMessage(inbox.error)}</div>
  const items = inbox.data?.items ?? []
  const cols = {
    pending: items.filter((i) => i.status === 'pending'),
    done: items.filter((i) => i.status === 'done'),
    skipped: items.filter((i) => i.status === 'skipped' || i.status === 'failed'),
  }
  return (
    <div>
      <PageHeader
        eyebrow="Espelho"
        title="Esteira & fila"
        description="Pending → enviado / skipped. Cupons entram na frente no worker."
      />
      <div className="v3-kanban">
        {(
          [
            ['pending', 'Pendentes', cols.pending],
            ['done', 'Enviados', cols.done],
            ['skipped', 'Pulados', cols.skipped],
          ] as const
        ).map(([key, label, list]) => (
          <section className="v3-column" key={key}>
            <h2>{label} · {list.length}</h2>
            {list.map((item) => (
              <article className="v3-column-item" key={item.id}>
                <small className="muted">{item.source_group_name || 'origem'}</small>
                <p style={{ margin: '0.35rem 0', whiteSpace: 'pre-wrap', fontSize: '0.88rem' }}>
                  {(item.body_text || '').slice(0, 180)}
                  {(item.body_text || '').length > 180 ? '…' : ''}
                </p>
                {item.status === 'pending' && (
                  <button className="button ghost" type="button" disabled={skip.isPending} onClick={() => skip.mutate(item.id)}>
                    Pular
                  </button>
                )}
                {item.skip_reason && <small className="muted">{item.skip_reason}</small>}
              </article>
            ))}
          </section>
        ))}
      </div>
    </div>
  )
}
