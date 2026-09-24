import { useState, type ReactNode } from 'react'
import { useAuth } from '../auth/useAuth'

export function Field({ label, error, children, className = '' }: { label: string; error?: string; children: ReactNode; className?: string }) {
  return <label className={`field ${className}`}><span>{label}</span>{children}{error && <small className="field-error">{error}</small>}</label>
}

export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><section className="modal" role="dialog" aria-modal="true" aria-label={title}><header><h2>{title}</h2><button className="icon-button" type="button" onClick={onClose} aria-label="Fechar">×</button></header>{children}</section></div>
}

export function StatusBadge({ value }: { value: string }) {
  return <span className={`status-badge status-${value}`}>{value.replaceAll('_', ' ')}</span>
}

export function TagsInput({ label, value, onChange, disabled = false }: { label: string; value: string[]; onChange: (next: string[]) => void; disabled?: boolean }) {
  const { user } = useAuth()
  const readOnly = disabled || user?.role !== 'admin'
  const [draft, setDraft] = useState('')
  const add = () => {
    const item = draft.trim()
    if (item && !value.includes(item)) onChange([...value, item])
    setDraft('')
  }
  return <div className="field tag-field"><span>{label}</span><div className="tags">{value.map((item) => <span className="tag" key={item}>{item}{!readOnly && <button type="button" aria-label={`Remover ${item}`} onClick={() => onChange(value.filter((entry) => entry !== item))}>×</button>}</span>)}</div>{!readOnly && <div className="tag-entry"><input value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ',') { event.preventDefault(); add() } }} /><button className="button ghost" type="button" onClick={add}>Adicionar</button></div>}</div>
}

export function ConfirmButton({ children, question, onConfirm, className = 'button danger-button' }: { children: ReactNode; question: string; onConfirm: () => void; className?: string }) {
  return <button className={className} type="button" onClick={() => { if (window.confirm(question)) onConfirm() }}>{children}</button>
}
