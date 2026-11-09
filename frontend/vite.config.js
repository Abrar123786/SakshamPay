import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Fail loudly instead of silently moving to another port: the backend's
    // CORS allowlist (FRONTEND_ORIGIN) expects exactly http://localhost:5173.
    strictPort: true,
  },
  preview: {
    port: 4173,
    strictPort: true,
  },
  // Vitest (npm test). Components are tested in jsdom with Testing Library.
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    include: ['src/**/*.test.{js,jsx}'],
    restoreMocks: true,
  },
})
