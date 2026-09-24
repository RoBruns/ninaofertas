import { Fragment, type ReactNode } from 'react'

// Marcação do WhatsApp usada nos templates: *negrito* e ~riscado~ (numa linha só).
const MARKUP = /(\*[^*\n]+\*|~[^~\n]+~)/g

export function WhatsAppText({ text }: { text: string }) {
  const parts: ReactNode[] = text.split(MARKUP).map((part, index) => {
    if (part.length > 2 && part.startsWith('*') && part.endsWith('*')) return <strong key={index}>{part.slice(1, -1)}</strong>
    if (part.length > 2 && part.startsWith('~') && part.endsWith('~')) return <s key={index}>{part.slice(1, -1)}</s>
    return <Fragment key={index}>{part}</Fragment>
  })
  return <>{parts}</>
}
