import { MoreHorizontal } from 'lucide-react'
import { cloneElement, isValidElement, useEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ConfirmDialog } from './Management'

export type MenuItem = { label?: string; icon?: ReactNode; onClick?: () => void; href?: string; danger?: boolean; separator?: boolean; labelOnly?: boolean; confirm?: string; consequence?: string; actionLabel?: string }

export function Menu({ label, trigger, items }: { label: string; trigger?: ReactElement; items: MenuItem[] }) {
  const menuRef = useRef<HTMLDivElement>(null)
  const [buttonElement, setButtonElement] = useState<HTMLButtonElement | null>(null), [open, setOpen] = useState(false), [position, setPosition] = useState({ top: 0, left: 0 }), [pending, setPending] = useState<MenuItem | null>(null)
  const close = (restore = false) => { setOpen(false); if (restore) queueMicrotask(() => buttonElement?.focus()) }
  const toggle = () => {
    if (!open && buttonElement) {
      const rect = buttonElement.getBoundingClientRect(), width = 220, height = Math.min(320, items.length * 40 + 16)
      setPosition({ left: Math.max(8, Math.min(window.innerWidth - width - 8, rect.right - width)), top: rect.bottom + height > window.innerHeight ? Math.max(8, rect.top - height - 6) : rect.bottom + 6 })
    }
    setOpen((value) => !value)
  }
  useEffect(() => { if (open) queueMicrotask(() => menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()) }, [open])
  useEffect(() => {
    if (!open) return
    const outside = (event: MouseEvent) => { if (!menuRef.current?.contains(event.target as Node) && !buttonElement?.contains(event.target as Node)) setOpen(false) }
    const dismiss = () => setOpen(false)
    document.addEventListener('mousedown', outside); window.addEventListener('scroll', dismiss, true); window.addEventListener('resize', dismiss)
    return () => { document.removeEventListener('mousedown', outside); window.removeEventListener('scroll', dismiss, true); window.removeEventListener('resize', dismiss) }
  }, [buttonElement, open])
  const keyDown = (event: React.KeyboardEvent) => {
    const options = Array.from(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []), current = options.indexOf(document.activeElement as HTMLElement)
    if (event.key === 'Escape') { event.preventDefault(); close(true) }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); options[(current + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length]?.focus() }
    if (event.key === 'Home') { event.preventDefault(); options[0]?.focus() }
    if (event.key === 'End') { event.preventDefault(); options.at(-1)?.focus() }
  }
  const choose = (item: MenuItem) => { close(); if (item.confirm) setPending(item); else item.onClick?.() }
  const triggerNode = trigger && isValidElement(trigger) ? cloneElement(trigger, { ref: setButtonElement, onClick: toggle, 'aria-haspopup': 'menu', 'aria-expanded': open, 'aria-label': label } as React.ComponentProps<'button'>) : <button ref={setButtonElement} className="icon-button" type="button" aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={toggle}><MoreHorizontal /></button>
  return <>{triggerNode}{open && createPortal(<div ref={menuRef} className="menu" role="menu" aria-label={label} style={position} onKeyDown={keyDown}>{items.map((item, index) => item.separator ? <div className="menu-separator" role="separator" key={index} /> : item.labelOnly ? <div className="menu-label" key={index}>{item.label}</div> : item.href ? <a className={`menu-item${item.danger ? ' danger' : ''}`} role="menuitem" href={item.href} key={index}>{item.icon}{item.label}</a> : <button className={`menu-item${item.danger ? ' danger' : ''}`} role="menuitem" type="button" onClick={() => choose(item)} key={index}>{item.icon}{item.label}</button>)}</div>, document.body)}{pending && <ConfirmDialog question={pending.confirm ?? ''} consequence={pending.consequence} actionLabel={pending.actionLabel ?? pending.label ?? 'Confirmar'} onCancel={() => { setPending(null); buttonElement?.focus() }} onConfirm={() => { pending.onClick?.(); setPending(null) }} />}</>
}
