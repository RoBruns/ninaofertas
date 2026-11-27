import { createBrowserRouter } from 'react-router-dom'
import { RequireAuth } from './auth/RequireAuth'
import { Layout } from './components/Layout'
import { Accounts } from './pages/Accounts'
import { BotDetail } from './pages/BotDetail'
import { Bots } from './pages/Bots'
import { Login } from './pages/Login'
import { AlertsPage, AuditPage, LogsPage, SalesPage } from './pages/LazyPages'
import { PhonesGroups } from './pages/PhonesGroups'
import { Users } from './pages/Users'
import { Platform } from './pages/Platform'
import { HomeDecisions } from './pages/v3/HomeDecisions'
import { Esteira } from './pages/v3/Esteira'
import { OfertasCatalogo } from './pages/v3/OfertasCatalogo'
import { FontesEspelho } from './pages/v3/FontesEspelho'
import { RadarCupons } from './pages/v3/RadarCupons'
import { VipPedidos } from './pages/v3/VipPedidos'
import { MonitorPreco } from './pages/v3/MonitorPreco'

export const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <Layout />,
        children: [
          { index: true, element: <HomeDecisions /> },
          { path: 'ofertas', element: <OfertasCatalogo /> },
          { path: 'esteira', element: <Esteira /> },
          { path: 'bots', element: <Bots /> },
          { path: 'bots/:id', element: <BotDetail /> },
          { path: 'fontes', element: <FontesEspelho /> },
          { path: 'cupons', element: <RadarCupons /> },
          { path: 'vip', element: <VipPedidos /> },
          { path: 'monitor', element: <MonitorPreco /> },
          { path: 'contas', element: <Accounts /> },
          { path: 'telefones', element: <PhonesGroups /> },
          { path: 'vendas', element: <SalesPage /> },
          { path: 'alertas', element: <AlertsPage /> },
          { path: 'logs', element: <LogsPage /> },
          { path: 'auditoria', element: <AuditPage /> },
          { path: 'usuarios', element: <Users /> },
          { path: 'plataforma', element: <Platform /> },
        ],
      },
    ],
  },
])
