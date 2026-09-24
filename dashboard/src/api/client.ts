import createClient, { type Middleware } from 'openapi-fetch'
import type { components, paths } from './schema'

export type User = components['schemas']['UserResponse']
export type OverviewResponse = components['schemas']['OverviewResponse']

let accessToken: string | null = null
let refreshPromise: Promise<string | null> | null = null
let sessionExpiredHandler: (() => void) | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function getAccessToken() {
  return accessToken
}

export function onSessionExpired(handler: (() => void) | null) {
  sessionExpiredHandler = handler
  return () => {
    if (sessionExpiredHandler === handler) sessionExpiredHandler = null
  }
}

export class ApiError extends Error {
  readonly status: number
  readonly fields: Readonly<Record<string, string>>
  readonly details: unknown

  constructor(message: string, status: number, fields: Readonly<Record<string, string>> = {}, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.fields = fields
    this.details = details
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : null
}

export function getApiFields(data: unknown) {
  const error = asRecord(asRecord(data)?.error)
  const rawFields = asRecord(error?.fields)
  if (!rawFields) return {}
  return Object.fromEntries(Object.entries(rawFields).flatMap(([key, value]) =>
    typeof value === 'string' ? [[key, value]] : [],
  ))
}

export function getApiError(data: unknown, fallback = 'Não foi possível concluir a solicitação.') {
  const message = asRecord(asRecord(data)?.error)?.message
  return typeof message === 'string' && message.trim() ? message : fallback
}


export function apiFailure(error: unknown, response: Response, fallback?: string): ApiError {
  return new ApiError(getApiError(error, fallback), response.status, getApiFields(error), error)
}

async function readRefreshToken(): Promise<string | null> {
  const response = await fetch('/api/auth/refresh', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) return null

  const body: unknown = await response.json()
  if (
    typeof body !== 'object' || body === null || !('access_token' in body) ||
    typeof body.access_token !== 'string'
  ) return null
  return body.access_token
}

export function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise
  refreshPromise = readRefreshToken()
    .then((token) => {
      setAccessToken(token)
      if (!token) sessionExpiredHandler?.()
      return token
    })
    .catch(() => {
      setAccessToken(null)
      sessionExpiredHandler?.()
      return null
    })
    .finally(() => { refreshPromise = null })
  return refreshPromise
}

const authMiddleware: Middleware = {
  async onRequest({ request }) {
    if (accessToken) request.headers.set('Authorization', `Bearer ${accessToken}`)
    return request
  },
  async onResponse({ request, response }) {
    const isAuthRequest = new URL(request.url).pathname.startsWith('/api/auth/')
    if (response.status !== 401 || isAuthRequest) return response
    const token = await refreshAccessToken()
    if (!token) return response
    const retry = new Request(request)
    retry.headers.set('Authorization', `Bearer ${token}`)
    const retryResponse = await fetch(retry)
    if (retryResponse.status === 401) {
      setAccessToken(null)
      sessionExpiredHandler?.()
    }
    return retryResponse
  },
}

export const api = createClient<paths>({
  baseUrl: '',
  credentials: 'same-origin',
  fetch: (request) => globalThis.fetch(request),
})
api.use(authMiddleware)

export async function loginRequest(email: string, password: string) {
  const { data, error } = await api.POST('/api/auth/login', { body: { email, password } })
  if (!data) throw new Error(getApiError(error, 'E-mail ou senha inválidos.'))
  setAccessToken(data.access_token)
  return data.user
}

export async function logoutRequest() {
  await api.POST('/api/auth/logout')
  setAccessToken(null)
}
