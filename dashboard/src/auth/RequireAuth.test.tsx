import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import { AuthContext, type AuthContextValue } from './AuthContext'
import { RequireAuth } from './RequireAuth'

function LoginTarget() {
  const location = useLocation()
  return <span>{`${location.pathname}${location.search}`}</span>
}

it('preserva a rota de origem ao voltar para o login', () => {
  const auth: AuthContextValue = { user: null, status: 'unauthenticated', login: vi.fn(), logout: vi.fn() }
  render(<AuthContext.Provider value={auth}><MemoryRouter initialEntries={['/bots?status=active']}><Routes><Route element={<RequireAuth />}><Route path="/bots" element={<span>privado</span>} /></Route><Route path="/login" element={<LoginTarget />} /></Routes></MemoryRouter></AuthContext.Provider>)
  expect(screen.getByText('/login?next=%2Fbots%3Fstatus%3Dactive')).toBeInTheDocument()
})
