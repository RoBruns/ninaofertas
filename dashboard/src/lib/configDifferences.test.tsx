import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { ConfigDifferences } from '../components/TestBotConfig'
import { configDifferences } from './configDifferences'
import { defaultSettings, type Bot } from '../api/management'

it('mostra caminhos e valores, ignora attribution e compara arrays e template', () => {
  const current: Bot = { id: '1', name: 'Produção', slug: 'prod', is_test: false, archived_at: null, test_source_bot_id: null, niche_id: null, phone_id: null, status: 'paused', settings: { ...defaultSettings, attribution: { ml_tag: 'prod' } }, message_template: 'Antigo', group_ids: [], account_ids: [], last_run_at: null, last_success_at: null, created_at: '', updated_at: '' }
  const next: Bot = { ...current, settings: { ...current.settings, attribution: { ml_tag: null }, filters: { ...current.settings.filters, preco_minimo: 123, lojas: ['Shopee'] } }, message_template: 'Novo' }
  expect(configDifferences(current, next).map((diff) => diff.path)).toEqual(['settings.filters.lojas', 'settings.filters.preco_minimo', 'message_template'])
  render(<ConfigDifferences current={current} next={next} />)
  expect(screen.getByText('settings.filters.preco_minimo').parentElement).toHaveTextContent('20 → 123')
  expect(screen.getByText('message_template').parentElement).toHaveTextContent('"Antigo" → "Novo"')
  expect(screen.queryByText(/attribution/)).not.toBeInTheDocument()
  expect(configDifferences(current, { ...current, settings: { ...current.settings, attribution: { ml_tag: 'outra' } } })).toEqual([])
})
