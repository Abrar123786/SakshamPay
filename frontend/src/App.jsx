import { createBrowserRouter, RouterProvider } from 'react-router'

import RouteError from './components/RouteError'
import AppLayout from './layouts/AppLayout'
import LandingPage from './pages/LandingPage'
import NotFoundPage from './pages/NotFoundPage'

/**
 * Route table. Later prompts add /login, /register, /dashboard, /pay,
 * /transactions/:id/review, /history and /alerts under the appropriate layouts.
 */
const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <LandingPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])

export default function App() {
  return <RouterProvider router={router} />
}
