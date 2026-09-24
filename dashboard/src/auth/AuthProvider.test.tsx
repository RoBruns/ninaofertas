import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { AuthProvider } from './AuthProvider'
import { useAuth } from './useAuth'

function json(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }) }
const user = { id: '00000000-0000-0000-0000-000000000001', email: 'admin@nina.test', name: 'Nina', role: 'admin', is_active: true, last_login_at: null, created_at: '2026-09-23T12:00:00Z' }

function Harness() {
  const auth = useAuth()
  return <div><span>{auth.status}</span><span>{auth.user?.name}</span><button onClick={() => void auth.login('admin@nina.test', 'secret')}>entrar</button></div>
}

beforeEach(() => { localStorage.clear(); sessionStorage.clear() })

it('boot com refresh 200 restaura a sessão sem mostrar estado deslogado', async () => {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    return Promise.resolve(url.includes('/refresh') ? json({ access_token: 'boot-token' }) : json(user))
  }))
  render(<AuthProvider><Harness /></AuthProvider>)
  expect(screen.getByText('loading')).toBeInTheDocument()
  expect(await screen.findByText('authenticated')).toBeInTheDocument()
  expect(screen.getByText('Nina')).toBeInTheDocument()
})

it('boot com refresh 401 vai para o estado de login', async () => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json({ error: { message: 'Expirada' } }, 401))))
  render(<AuthProvider><Harness /></AuthProvider>)
  expect(await screen.findByText('unauthenticated')).toBeInTheDocument()
})

it('login guarda token apenas em memória', async () => {
  let calls = 0
  vi.stubGlobal('fetch', vi.fn(() => {
    calls += 1
    return Promise.resolve(calls === 1 ? json({}, 401) : json({ access_token: 'login-token', user }))
  }))
  render(<AuthProvider><Harness /></AuthProvider>)
  await screen.findByText('unauthenticated')
  await userEvent.click(screen.getByRole('button', { name: 'entrar' }))
  await waitFor(() => expect(screen.getByText('authenticated')).toBeInTheDocument())
  expect(localStorage).toHaveLength(0)
  expect(sessionStorage).toHaveLength(0)
})
