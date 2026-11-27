/** Cliente fino para endpoints V3 até regenerar o OpenAPI. */
import { getAccessToken, ApiError } from '../api/client'

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const token = getAccessToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(path, { ...init, headers, credentials: 'include' })
  if (!response.ok) {
    let details: unknown
    try {
      details = await response.json()
    } catch {
      details = undefined
    }
    const message =
      (details as { error?: { message?: string } })?.error?.message ||
      response.statusText ||
      'Falha na API'
    throw new ApiError(message, response.status, {}, details)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const v3api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

export type DecisionItem = {
  id: string
  severity: 'urgent' | 'warn' | 'info'
  title: string
  detail: string
  href: string
}

export type DecisionsResponse = {
  items: DecisionItem[]
  stats: {
    mirror_pending: number
    open_alerts: number
    cups_active: number
    vip_waiting: number
    monitors_hit: number
  }
}
