import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

const storefrontApiOrigin = process.env.SHOP_API_ORIGIN ?? 'http://127.0.0.1:8011'
const customerServiceOrigin = process.env.SHOP_CUSTOMER_SERVICE_MODE === 'demo'
  ? process.env.SHOP_CUSTOMER_SERVICE_ORIGIN
  : undefined

function customerServiceDemoRedirect(): Plugin {
  return {
    name: 'customer-service-demo-redirect',
    enforce: 'pre',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (!customerServiceOrigin || request.method !== 'GET' || !request.url) {
          next()
          return
        }

        let pathname: string
        try {
          pathname = new URL(request.url, 'http://vite.local').pathname
        } catch {
          next()
          return
        }
        if (pathname !== '/customer-service.html') {
          next()
          return
        }

        const target = new URL('/customer-service.html', customerServiceOrigin)
        response.writeHead(302, { Location: target.toString(), 'Cache-Control': 'no-store' })
        response.end()
      })
    },
  }
}

export default defineConfig({
  plugins: [customerServiceDemoRedirect(), react()],
  server: {
    proxy: {
      '/api': {
        target: storefrontApiOrigin,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyRequest, request) => {
            if (request.headers.origin) {
              proxyRequest.setHeader('origin', new URL(storefrontApiOrigin).origin)
            }
          })
        },
      },
    },
  },
})
