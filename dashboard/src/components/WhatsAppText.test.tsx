import { render } from '@testing-library/react'
import { expect, it } from 'vitest'
import { WhatsAppText } from './WhatsAppText'

it('mostra *negrito* e ~riscado~ como o WhatsApp, sem os marcadores', () => {
  const { container } = render(<WhatsAppText text={'De ~R$ 115~ por *R$ 92*'} />)
  expect(container.querySelector('strong')).toHaveTextContent('R$ 92')
  expect(container.querySelector('s')).toHaveTextContent('R$ 115')
  expect(container).toHaveTextContent('De R$ 115 por R$ 92')
})

it('não interpreta HTML do template', () => {
  const { container } = render(<WhatsAppText text={'<b>x</b> *ok*'} />)
  expect(container.querySelector('b')).toBeNull()
  expect(container).toHaveTextContent('<b>x</b> ok')
})
