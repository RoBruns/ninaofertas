import { lazy } from 'react'

export const OverviewPage = lazy(() => import('./Overview').then((module) => ({ default: module.Overview })))
export const PerformancePage = lazy(() => import('./Performance').then((module) => ({ default: module.Performance })))
export const SalesPage = lazy(() => import('./Sales').then((module) => ({ default: module.Sales })))
export const ExpensesPage = lazy(() => import('./Expenses').then((module) => ({ default: module.Expenses })))
export const CampaignsPage = lazy(() => import('./Campaigns').then((module) => ({ default: module.Campaigns })))
export const AlertsPage = lazy(() => import('./Alerts').then((module) => ({ default: module.Alerts })))
export const LogsPage = lazy(() => import('./Logs').then((module) => ({ default: module.Logs })))
export const AuditPage = lazy(() => import('./Audit').then((module) => ({ default: module.Audit })))
