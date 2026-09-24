import { createContext } from 'react'

export type ToastKind = 'info' | 'success' | 'error'
export type ToastValue = { showToast: (message: string, kind?: ToastKind) => void }
export const ToastContext = createContext<ToastValue | null>(null)
