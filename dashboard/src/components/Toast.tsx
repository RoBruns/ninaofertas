import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react'
import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { ToastContext, type ToastKind } from './toastContext'
type ToastItem = { id: number; message: string; kind: ToastKind }
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const remove = useCallback((id: number) => setToasts((items) => items.filter((item) => item.id !== id)), [])
  const showToast = useCallback((message: string, kind: ToastKind = 'info') => { const id = Date.now() + Math.random(); setToasts((items) => [...items, { id, message, kind }].slice(-3)); window.setTimeout(() => remove(id), kind === 'error' ? 7000 : 4000) }, [remove])
  const value = useMemo(() => ({ showToast }), [showToast])
  return <ToastContext.Provider value={value}>{children}<div className="toast-stack" aria-live="polite">{toasts.map((toast) => { const Icon = toast.kind === 'success' ? CheckCircle2 : toast.kind === 'error' ? AlertCircle : Info; return <div className={`toast ${toast.kind}`} role="status" key={toast.id}><Icon /><span>{toast.message}</span><button type="button" aria-label="Fechar aviso" onClick={() => remove(toast.id)}><X /></button></div> })}</div></ToastContext.Provider>
}
