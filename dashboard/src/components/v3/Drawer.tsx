import type { ReactNode } from 'react'
import { X } from 'lucide-react'

export function Drawer({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string
  subtitle?: string
  onClose: () => void
  children: ReactNode
}) {
  return (
    <>
      <button type="button" className="v3-drawer-backdrop" aria-label="Fechar" onClick={onClose} />
      <aside className="v3-drawer" role="dialog" aria-modal="true" aria-label={title}>
        <header>
          <div>
            <h2>{title}</h2>
            {subtitle ? <p className="muted">{subtitle}</p> : null}
          </div>
          <button type="button" className="button ghost" onClick={onClose} aria-label="Fechar">
            <X size={18} />
          </button>
        </header>
        <div className="body">{children}</div>
      </aside>
    </>
  )
}
