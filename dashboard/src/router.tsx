import { createBrowserRouter } from 'react-router-dom'
import { RequireAuth } from './auth/RequireAuth'
import { Layout } from './components/Layout'
import { Accounts } from './pages/Accounts'
import { BotDetail } from './pages/BotDetail'
import { Bots } from './pages/Bots'
import { Login } from './pages/Login'
import { Overview } from './pages/Overview'
import { PhonesGroups } from './pages/PhonesGroups'
import { Placeholder } from './pages/Placeholder'
import { Users } from './pages/Users'

const placeholders = [
  ['vendas', 'Vendas'], ['despesas', 'Despesas'], ['campanhas', 'Campanhas'],
  ['alertas', 'Alertas'], ['logs', 'Logs técnicos'], ['auditoria', 'Auditoria'],
].map(([path, title]) => ({ path, element: <Placeholder title={title} /> }))

export const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  { element: <RequireAuth />, children: [{ element: <Layout />, children: [
    { index: true, element: <Overview /> },
    { path: 'bots', element: <Bots /> },
    { path: 'bots/:id', element: <BotDetail /> },
    { path: 'contas', element: <Accounts /> },
    { path: 'telefones', element: <PhonesGroups /> },
    { path: 'telefones-grupos', element: <PhonesGroups /> },
    { path: 'usuarios', element: <Users /> },
    ...placeholders,
  ] }] },
])
