import { createBrowserRouter, RouterProvider } from 'react-router'

import AuthProvider from './context/AuthProvider'
import { createRoutes } from './routes'

const router = createBrowserRouter(createRoutes())

export default function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  )
}
