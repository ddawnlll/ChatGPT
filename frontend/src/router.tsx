import { createRootRoute, createRoute, createRouter, Outlet } from '@tanstack/react-router'
import { ChatShell } from './ui/chat-shell'

const rootRoute = createRootRoute({
  component: () => <Outlet />,
})

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: ChatShell,
})

const chatRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/chat/$chatId',
  component: ChatShell,
})

const routeTree = rootRoute.addChildren([indexRoute, chatRoute])

export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
