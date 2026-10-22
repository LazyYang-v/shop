import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: process.env.SHOP_API_ORIGIN ?? 'http://127.0.0.1:8011',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyRequest, request) => {
            if (request.headers.origin) {
              proxyRequest.setHeader('origin', 'http://127.0.0.1:8011')
            }
          })
        },
      },
    },
  },
})
