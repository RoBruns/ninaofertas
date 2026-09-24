import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { DataWarnings } from './DataWarnings'
import { ConfirmButton, StatusBadge } from './Management'
import { Menu } from './Menu'
import { Price } from './Price'

it('abre o menu, navega pelo teclado e devolve o foco ao fechar', async () => {
  const user = userEvent.setup()
  render(<Menu label="Mais ações" items={[{ label: 'Primeira' }, { label: 'Segunda' }]} />)
  const trigger = screen.getByRole('button', { name: 'Mais ações' })
  await user.click(trigger)
  const menu = screen.getByRole('menu')
  expect(within(menu).getByRole('menuitem', { name: 'Primeira' })).toHaveFocus()
  await user.keyboard('{ArrowDown}')
  expect(within(menu).getByRole('menuitem', { name: 'Segunda' })).toHaveFocus()
  await user.keyboard('{Escape}')
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
})

it('confirma item de menu antes de executar', async () => {
  const action = vi.fn(), user = userEvent.setup()
  render(<Menu label="Mais ações" items={[{ label: 'Excluir', confirm: 'Excluir item?', onClick: action }]} />)
  await user.click(screen.getByRole('button', { name: 'Mais ações' }))
  await user.click(screen.getByRole('menuitem', { name: 'Excluir' }))
  expect(action).not.toHaveBeenCalled()
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Excluir' }))
  expect(action).toHaveBeenCalledOnce()
})

it('ConfirmButton cancela e confirma sem usar confirmação nativa', async () => {
  const action = vi.fn(), user = userEvent.setup()
  render(<ConfirmButton question="Desativar item?" onConfirm={action}>Desativar</ConfirmButton>)
  await user.click(screen.getByRole('button', { name: 'Desativar' }))
  await user.click(screen.getByRole('button', { name: 'Cancelar' }))
  expect(action).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: 'Desativar' }))
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Desativar' }))
  expect(action).toHaveBeenCalledOnce()
})

it('traduz badges conhecidos e limpa valores desconhecidos', () => {
  const { rerender } = render(<StatusBadge value="paused" />)
  expect(screen.getByText('Pausado')).toHaveClass('status-paused')
  rerender(<StatusBadge value="custom_value" />)
  expect(screen.getByText('custom value')).toBeInTheDocument()
})

it('separa as partes de dinheiro e mantém fallback puro', () => {
  const { rerender } = render(<Price value="R$ 1.234,56" />)
  const price = screen.getByLabelText('R$ 1.234,56')
  expect(within(price).getByText('R$')).toHaveClass('price-cur')
  expect(within(price).getByText('1.234')).toHaveClass('price-int')
  expect(within(price).getByText(',56')).toHaveClass('price-cents')
  rerender(<Price value="sem dados" />)
  expect(screen.getByText('sem dados')).toBeInTheDocument()
})

it('deduplica e humaniza avisos de dados', () => {
  render(<DataWarnings warnings={['buyer_hash ausente', 'buyer_hash ausente']} />)
  expect(screen.getByText('Dados incompletos (1)')).toBeInTheDocument()
  expect(screen.getByText('identificação do comprador ausente')).toBeInTheDocument()
})
