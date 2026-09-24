import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, loginRequest, logoutRequest, onSessionExpired, refreshAccessToken, setAccessToken, type User } from '../api/client'
import { AuthContext, type AuthStatus } from './AuthContext'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [status, setStatus] = useState<AuthStatus>('loading')

  const expireSession = useCallback(() => {
    setAccessToken(null)
    setUser(null)
    setStatus('unauthenticated')
  }, [])

  useEffect(() => onSessionExpired(expireSession), [expireSession])
  useEffect(() => {
    let active = true
    async function restoreSession() {
      try {
        const token = await refreshAccessToken()
        if (!token || !active) {
          if (active) expireSession()
          return
        }
        const { data } = await api.GET('/api/auth/me')
        if (!active) return
        if (data) {
          setUser(data)
          setStatus('authenticated')
        } else expireSession()
      } catch {
        if (active) expireSession()
      }
    }
    void restoreSession()
    return () => { active = false }
  }, [expireSession])

  const login = useCallback(async (email: string, password: string) => {
    const loggedUser = await loginRequest(email, password)
    setUser(loggedUser)
    setStatus('authenticated')
  }, [])
  const logout = useCallback(async () => {
    try {
      await logoutRequest()
    } catch {
      // A sessão local deve terminar mesmo se a API estiver indisponível.
    } finally {
      expireSession()
    }
  }, [expireSession])
  const value = useMemo(() => ({ user, status, login, logout }), [login, logout, status, user])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
