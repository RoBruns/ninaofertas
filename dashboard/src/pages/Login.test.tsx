import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import { AuthContext, type AuthContextValue } from '../auth/AuthContext'
import { Login } from './Login'

it('mostra a mensagem do envelope de erro da API', async () => {
  const value: AuthContextValue = { user: null, status: 'unauthenticated', login: vi.fn().mockRejectedValue(new Error('Credenciais incorretas')), logout: vi.fn() }
  render(<MemoryRouter><AuthContext.Provider value={value}><Login /></AuthContext.Provider></MemoryRouter>)
  await userEvent.type(screen.getByLabelText('E-mail'), 'x@example.com')
  await userEvent.type(screen.getByLabelText('Senha'), 'errada')
  await userEvent.click(screen.getByRole('button', { name: 'Entrar' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Credenciais incorretas')
})
