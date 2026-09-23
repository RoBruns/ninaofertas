import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Em desenvolvimento, /api é repassado para a FastAPI local (uvicorn na 8000).
// Assim o front usa sempre caminho relativo e o cookie de refresh
// (SameSite=Strict, path=/api/auth) funciona sem CORS.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: false },
    },
  },
})
