import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { WorkerAlert } from './WorkerAlert'

afterEach(() => { vi.unstubAllGlobals() })

it('mostra offline em Brasília e remove a faixa quando volta online', async () => {
  let status = 'offline'
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
    status: 'ok', db: 'ok', worker_status: status,
    worker_last_seen: '2026-09-30T13:00:00Z', worker_offline_since: '2026-09-30T13:05:00Z',
  }), { headers: { 'Content-Type': 'application/json' } })))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={queryClient}><WorkerAlert /></QueryClientProvider>)
  expect(await screen.findByRole('alert')).toHaveTextContent('Worker parado desde 10:00 — nenhuma oferta está sendo enviada.')
  status = 'online'
  await act(async () => { await queryClient.invalidateQueries({ queryKey: ['worker-health'] }) })
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  queryClient.clear()
})

it('mostra texto neutro quando o worker nunca conectou', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ status: 'ok', db: 'ok', worker_status: 'unknown', worker_last_seen: null, worker_offline_since: null }), { headers: { 'Content-Type': 'application/json' } })))
  const queryClient = new QueryClient()
  render(<QueryClientProvider client={queryClient}><WorkerAlert /></QueryClientProvider>)
  expect(await screen.findByRole('status')).toHaveTextContent('Worker ainda não se conectou.')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  queryClient.clear()
})
