import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, getAccessToken, getApiError, loginRequest, onSessionExpired, setAccessToken } from './client'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const overview = {
  period: { from: '2026-08-25', to: '2026-09-23' },
  kpis: {
    revenue: { value: '1.00', previous: null, change_pct: null }, commission: { value: '1.00', previous: null, change_pct: null }, commission_pending: { value: null, previous: null, change_pct: null },
    orders: { value: 1, previous: null, change_pct: null }, buyers: { value: 1, previous: null, change_pct: null }, spend: { value: '0.10', previous: null, change_pct: null }, traffic_spend: { value: null, previous: null, change_pct: null }, profit: { value: '0.90', previous: null, change_pct: null },
    roi: { value: 9, previous: null, change_pct: null }, roas: { value: 10, previous: null, change_pct: null }, cost_per_sale: { value: '0.10', previous: null, change_pct: null }, cost_per_buyer: { value: '0.10', previous: null, change_pct: null }, cost_per_join: { value: null, previous: null, change_pct: null }, group_joins: { value: 0, previous: null, change_pct: null }, sends: { value: 1, previous: null, change_pct: null }, clicks: { value: 1, previous: null, change_pct: null }, conversion: { value: 1, previous: null, change_pct: null },
  }, warnings: [],
}

beforeEach(() => { setAccessToken('old-token') })
afterEach(() => { setAccessToken(null); onSessionExpired(null); vi.unstubAllGlobals() })

describe('middleware de autenticação', () => {
  it('extrai a mensagem segura do envelope da API', () => {
    expect(getApiError({ error: { code: 'BAD', message: 'Mensagem amigável' } })).toBe('Mensagem amigável')
  })

  it('propaga no login a mensagem do envelope da API', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json({ error: { code: 'UNAUTHORIZED', message: 'Credenciais incorretas' } }, 401))))
    await expect(loginRequest('x@example.com', 'errada')).rejects.toThrow('Credenciais incorretas')
  })
  it('faz um refresh, repete a requisição uma vez e tem sucesso', async () => {
    let overviewCalls = 0
    let refreshCalls = 0
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.includes('/api/auth/refresh')) { refreshCalls += 1; return Promise.resolve(json({ access_token: 'new-token' })) }
      overviewCalls += 1
      return Promise.resolve(overviewCalls === 1 ? json({ error: { code: 'UNAUTHORIZED', message: 'Expirou' } }, 401) : json(overview))
    }))
    const result = await api.GET('/api/metrics/overview')
    expect(result.data?.period.to).toBe('2026-09-23')
    expect(refreshCalls).toBe(1)
    expect(overviewCalls).toBe(2)
    expect(getAccessToken()).toBe('new-token')
  })

  it('limpa a sessão quando o 401 persiste', async () => {
    const expired = vi.fn()
    onSessionExpired(expired)
    let protectedCalls = 0
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.includes('/api/auth/refresh')) return Promise.resolve(json({ access_token: 'still-invalid' }))
      protectedCalls += 1
      return Promise.resolve(json({}, 401))
    }))
    await api.GET('/api/metrics/overview')
    expect(expired).toHaveBeenCalledOnce()
    expect(getAccessToken()).toBeNull()
    expect(protectedCalls).toBe(2)
  })

  it('compartilha um único refresh entre três requisições simultâneas', async () => {
    let initialCalls = 0
    let refreshCalls = 0
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.includes('/api/auth/refresh')) {
        refreshCalls += 1
        return new Promise<Response>((resolve) => window.setTimeout(() => resolve(json({ access_token: 'shared-token' })), 5))
      }
      initialCalls += 1
      return Promise.resolve(initialCalls <= 3 ? json({}, 401) : json(overview))
    }))
    const results = await Promise.all([api.GET('/api/metrics/overview'), api.GET('/api/metrics/overview'), api.GET('/api/metrics/overview')])
    expect(results.every((result) => result.data?.warnings.length === 0)).toBe(true)
    expect(refreshCalls).toBe(1)
  })
})
