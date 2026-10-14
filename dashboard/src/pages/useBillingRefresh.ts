import { useQueryClient } from '@tanstack/react-query'

export function useBillingRefresh() {
  const client = useQueryClient()
  return () => Promise.all(['platform-tenants', 'platform-plans', 'platform-metrics', 'subscription-events'].map((key) => client.invalidateQueries({ queryKey: [key] })))
}
