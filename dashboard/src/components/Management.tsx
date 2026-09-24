import { AlertTriangle, X } from 'lucide-react'
import { Children, cloneElement, isValidElement, useEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useAuth } from '../auth/useAuth'

export function Field({ label, error, children, className = '' }: { label: string; error?: string; children: ReactNode; className?: string }) {
  return <label className={`field ${className}`}><span>{label}</span>{children}{error && <small className="field-error">{error}</small>}</label>
}

export function Modal({ title, children, onClose, size }: { title: string; children: ReactNode; onClose: () => void; size?: 'wide' }) {
  const dialog = useRef<HTMLElement>(null), previous = useRef<HTMLElement | null>(null)
  useEffect(() => {
    previous.current = document.activeElement as HTMLElement
    queueMicrotask(() => dialog.current?.querySelector<HTMLElement>('input, select, textarea, button:not([aria-label="Fechar"])')?.focus())
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('keydown', escape); previous.current?.focus() }
  }, [onClose])
  const splitActions = (nodes: ReactNode) => {
    const parts = Children.toArray(nodes)
    const index = parts.findIndex((part) => isValidElement<{ className?: string }>(part) && part.props.className?.split(' ').includes('form-actions'))
    return index < 0 ? { body: parts, actions: null } : { body: parts.filter((_, itemIndex) => itemIndex !== index), actions: parts[index] }
  }
  let content: ReactNode
  if (isValidElement<{ className?: string; children?: ReactNode }>(children) && children.type === 'form') {
    const { body, actions } = splitActions(children.props.children)
    content = cloneElement(children as ReactElement<{ className?: string }>, { className: 'modal-form' }, <div className={`modal-body ${children.props.className || ''}`}>{body}</div>, actions)
  } else {
    const { body, actions } = splitActions(children)
    content = <><div className="modal-body">{body}</div>{actions}</>
  }
  return createPortal(<div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><section ref={dialog} className={`modal${size === 'wide' ? ' wide-modal' : ''}`} role="dialog" aria-modal="true" aria-label={title}><header><h2>{title}</h2><button className="icon-button" type="button" onClick={onClose} aria-label="Fechar"><X /></button></header>{content}</section></div>, document.body)
}

const statusLabels: Record<string, string> = {
  active: 'Ativo', paused: 'Pausado', disabled: 'Desativado', valid: 'Válida', invalid: 'Inválida', expired: 'Expirada', expiring: 'Expirando', unknown: 'Desconhecido', connected: 'Conectado', disconnected: 'Desconectado', banned: 'Banido', error: 'Erro', ok: 'OK', success: 'Sucesso', failed: 'Falhou', running: 'Em execução', open: 'Aberto', acknowledged: 'Reconhecido', resolved: 'Resolvido', archived: 'Arquivado', completed: 'Concluída', admin: 'Administrador', operator: 'Operador', viewer: 'Leitor',
}
export function StatusBadge({ value }: { value: string }) { return <span className={`status-badge status-${value}`}>{statusLabels[value] ?? value.replaceAll('_', ' ')}</span> }

export function TagsInput({ label, value, onChange, disabled = false }: { label: string; value: string[]; onChange: (next: string[]) => void; disabled?: boolean }) {
  const { user } = useAuth(), readOnly = disabled || user?.role !== 'admin', [draft, setDraft] = useState('')
  const add = () => { const item = draft.trim(); if (item && !value.includes(item)) onChange([...value, item]); setDraft('') }
  return <div className="field tag-field"><span>{label}</span><div className="tags">{value.map((item) => <span className="tag" key={item}>{item}{!readOnly && <button type="button" aria-label={`Remover ${item}`} onClick={() => onChange(value.filter((entry) => entry !== item))}><X /></button>}</span>)}</div>{!readOnly && <div className="tag-entry"><input value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ',') { event.preventDefault(); add() } }} /><button className="button ghost" type="button" onClick={add}>Adicionar</button></div>}</div>
}

export function ConfirmDialog({ question, consequence, actionLabel, onCancel, onConfirm }: { question: string; consequence?: string; actionLabel: string; onCancel: () => void; onConfirm: () => void }) {
  return <Modal title="Confirmar ação" onClose={onCancel}><div className="confirm-body"><span className="confirm-icon"><AlertTriangle /></span><div><strong>{question}</strong>{consequence && <p className="muted">{consequence}</p>}</div></div><div className="form-actions"><button className="button ghost" type="button" onClick={onCancel}>Cancelar</button><button className="button danger-solid" type="button" onClick={onConfirm}>{actionLabel}</button></div></Modal>
}

export function ConfirmButton({ children, question, onConfirm, className = 'button danger-button' }: { children: ReactNode; question: string; onConfirm: () => void; className?: string }) {
  const [open, setOpen] = useState(false), label = typeof children === 'string' ? children : 'Confirmar'
  return <><button className={className} type="button" onClick={() => setOpen(true)}>{children}</button>{open && <ConfirmDialog question={question} actionLabel={label} onCancel={() => setOpen(false)} onConfirm={() => { setOpen(false); onConfirm() }} />}</>
}
