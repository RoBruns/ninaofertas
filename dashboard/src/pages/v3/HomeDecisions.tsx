import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { PageHeader } from '../../components/v3/PageHeader'
import { Spinner } from '../../components/Spinner'
import { errorMessage } from '../../api/management'
import { v3api, type DecisionsResponse } from '../../v3/api'

export function HomeDecisions() {
  const decisions = useQuery({
    queryKey: ['v3-decisions'],
    queryFn: () => v3api.get<DecisionsResponse>('/api/v3/decisions'),
    refetchInterval: 20_000,
  })
  if (decisions.isLoading) return <Spinner label="Carregando decisões" />
  if (decisions.isError) return <div className="page-error">{errorMessage(decisions.error)}</div>
  const data = decisions.data!
  return (
    <div>
      <PageHeader
        eyebrow="Operação"
        title="O que fazer agora"
        description="Fila de decisões — espelho, canais e radar antes de KPI."
      />
      <div className="v3-stat-row">
        <div className="v3-stat">
          <strong>{data.stats.mirror_pending}</strong>
          <span>Pending espelho</span>
        </div>
        <div className="v3-stat">
          <strong>{data.stats.open_alerts}</strong>
          <span>Alertas</span>
        </div>
        <div className="v3-stat">
          <strong>{data.stats.cups_active}</strong>
          <span>Cupons ativos</span>
        </div>
        <div className="v3-stat">
          <strong>{data.stats.vip_waiting}</strong>
          <span>VIP aguardando</span>
        </div>
        <div className="v3-stat">
          <strong>{data.stats.monitors_hit}</strong>
          <span>Preço-alvo</span>
        </div>
      </div>
      <div className="v3-decision-list">
        {data.items.map((item) => (
          <article
            key={item.id}
            className={`v3-decision ${item.severity === 'urgent' ? 'urgent' : item.severity}`}
          >
            <span className="v3-decision-mark" aria-hidden />
            <div>
              <h3>{item.title}</h3>
              <p>{item.detail}</p>
            </div>
            <Link className="button primary" to={item.href}>
              Abrir
            </Link>
          </article>
        ))}
      </div>
    </div>
  )
}
