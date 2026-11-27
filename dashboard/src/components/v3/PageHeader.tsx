import type { ReactNode } from 'react'

export function PageHeader({
  eyebrow = 'Nina',
  title,
  description,
  actions,
}: {
  eyebrow?: string
  title: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <div className="v3-page-header">
      <div>
        {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {actions ? <div className="form-actions">{actions}</div> : null}
    </div>
  )
}
