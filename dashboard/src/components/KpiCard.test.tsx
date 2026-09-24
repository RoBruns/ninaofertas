import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { KpiCard } from './KpiCard'

it('mostra sem dados e nenhuma seta quando o KPI é nulo', () => {
  render(<KpiCard label="ROI" value="sem dados" change={null} />)
  expect(screen.getByText('sem dados')).toBeInTheDocument()
  expect(screen.getByText('sem comparação')).toBeInTheDocument()
  expect(screen.queryByText(/↑|↓|→/)).not.toBeInTheDocument()
})
