import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Spinner } from '../components/Spinner'
import { useAuth } from './useAuth'

export function RequireAuth() {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <Spinner fullScreen label="Restaurando sessão" />
  if (status === 'unauthenticated') {
    const next = `${location.pathname}${location.search}`
    return <Navigate replace to={`/login?next=${encodeURIComponent(next)}`} />
  }
  return <Outlet />
}
