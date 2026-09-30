import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Info } from 'lucide-react'
import { api, apiFailure } from '../api/client'

export function WorkerAlert() {
  const { data } = useQuery({
    queryKey: ['worker-health'],
    queryFn: async () => {
      const result = await api.GET('/api/health')
      if (!result.data) throw apiFailure(result.error, result.response)
      return result.data
    },
    refetchInterval: 60_000,
  })
  if (!data || data.worker_status === 'online') return null
  if (data.worker_status === 'unknown') return <div className="worker-alert worker-unknown" role="status"><Info aria-hidden="true" />Worker ainda não se conectou.</div>
  const time = new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(data.worker_last_seen ?? data.worker_offline_since!))
  return <div className="worker-alert" role="alert"><AlertTriangle aria-hidden="true" />Worker parado desde {time} — nenhuma oferta está sendo enviada.</div>
}
