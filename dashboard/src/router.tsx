import { createBrowserRouter } from 'react-router-dom'
import { RequireAuth } from './auth/RequireAuth'
import { Layout } from './components/Layout'
import { Accounts } from './pages/Accounts'
import { BotDetail } from './pages/BotDetail'
import { Bots } from './pages/Bots'
import { Login } from './pages/Login'
import { AlertsPage, AuditPage, CampaignsPage, ExpensesPage, LogsPage, OverviewPage, PerformancePage, SalesPage } from './pages/LazyPages'
import { PhonesGroups } from './pages/PhonesGroups'
import { Users } from './pages/Users'

export const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  { element: <RequireAuth />, children: [{ element: <Layout />, children: [
    { index: true, element: <OverviewPage /> },
    { path: 'desempenho', element: <PerformancePage /> },
    { path: 'bots', element: <Bots /> },
    { path: 'bots/:id', element: <BotDetail /> },
    { path: 'contas', element: <Accounts /> },
    { path: 'telefones', element: <PhonesGroups /> },
    { path: 'telefones-grupos', element: <PhonesGroups /> },
    { path: 'vendas', element: <SalesPage /> },
    { path: 'despesas', element: <ExpensesPage /> },
    { path: 'campanhas', element: <CampaignsPage /> },
    { path: 'alertas', element: <AlertsPage /> },
    { path: 'logs', element: <LogsPage /> },
    { path: 'auditoria', element: <AuditPage /> },
    { path: 'usuarios', element: <Users /> },
  ] }] },
])
