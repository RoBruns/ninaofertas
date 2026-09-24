import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { ImportErrors } from './ImportErrors'

it('mostra erros por linha e informa que CSV recusado não importa nada', () => {
  render(<ImportErrors errors={[{ line: 3, message: 'pedido inválido' }, { line: 8, message: 'data ausente' }]} />)
  const alert = screen.getByRole('alert')
  expect(alert).toHaveTextContent('nenhuma linha foi importada')
  expect(alert).toHaveTextContent('Linha 3: pedido inválido')
  expect(alert).toHaveTextContent('Linha 8: data ausente')
})
