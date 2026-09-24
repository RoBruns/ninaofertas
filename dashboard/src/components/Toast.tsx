import { useCallback, useMemo, useState, type ReactNode } from 'react'

import { ToastContext, type ToastKind } from './toastContext'

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<{ message: string; kind: ToastKind } | null>(null)
  const showToast = useCallback((message: string, kind: ToastKind = 'info') => {
    setToast({ message, kind })
    window.setTimeout(() => setToast(null), 4000)
  }, [])
  const value = useMemo(() => ({ showToast }), [showToast])
  return <ToastContext.Provider value={value}>{children}{toast && <div className={`toast ${toast.kind}`} role="status">{toast.message}<button type="button" aria-label="Fechar aviso" onClick={() => setToast(null)}>×</button></div>}</ToastContext.Provider>
}
