import { createBrowserRouter, RouterProvider } from 'react-router'

import { createRoutes } from './routes'

const router = createBrowserRouter(createRoutes())

export default function App() {
  return <RouterProvider router={router} />
}
