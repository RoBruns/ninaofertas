import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { KpiCard } from './KpiCard'

it('mostra sem dados e nenhuma seta quando o KPI é nulo', () => {
  render(<KpiCard label="ROI" value="sem dados" change={null} />)
  expect(screen.getByText('sem dados')).toBeInTheDocument()
  expect(screen.getByText('sem comparação')).toBeInTheDocument()
  expect(screen.queryByText(/↑|↓|→/)).not.toBeInTheDocument()
})

it('marca aumento de custo como pior e queda como melhor, mantendo a seta da variação', () => {
  const { rerender, container } = render(<KpiCard label="Investimento" value="R$ 120,00" change={87.506} higherIsBetter={false} />)
  expect(screen.getByText('+87,5%')).toHaveClass('negative')
  expect(container.querySelector('.lucide-trending-up')).toBeInTheDocument()
  rerender(<KpiCard label="Custo por venda" value="R$ 10,00" change={-5} higherIsBetter={false} />)
  expect(screen.getByText('-5,0%')).toHaveClass('positive')
  expect(container.querySelector('.lucide-trending-down')).toBeInTheDocument()
})
