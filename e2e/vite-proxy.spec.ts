import { expect, test } from '@playwright/test'
import { createServer as createViteServer } from 'vite'

test('development storefront keeps its API and redirects customer service to the isolated demo', async () => {
  const previousStorefrontOrigin = process.env.SHOP_API_ORIGIN
  const previousCustomerServiceOrigin = process.env.SHOP_CUSTOMER_SERVICE_ORIGIN
  const previousCustomerServiceMode = process.env.SHOP_CUSTOMER_SERVICE_MODE
  process.env.SHOP_API_ORIGIN = 'http://127.0.0.1:8011'
  process.env.SHOP_CUSTOMER_SERVICE_MODE = 'demo'
  process.env.SHOP_CUSTOMER_SERVICE_ORIGIN = 'http://127.0.0.1:18011'
  let vite: Awaited<ReturnType<typeof createViteServer>> | undefined

  try {
    vite = await createViteServer({
      configFile: 'vite.config.ts',
      logLevel: 'silent',
      server: { host: '127.0.0.1', port: 0 },
    })
    await vite.listen()
    const address = vite.httpServer?.address()
    expect(address && typeof address !== 'string').toBeTruthy()
    if (!address || typeof address === 'string') throw new Error('Vite did not bind a TCP port')
    const origin = `http://127.0.0.1:${address.port}`

    const storefront = await fetch(`${origin}/api/health`, {
      headers: { origin, referer: `${origin}/` },
    })
    expect(storefront.status).toBe(200)

    const customerService = await fetch(`${origin}/customer-service.html`, { redirect: 'manual' })
    expect(customerService.status).toBe(302)
    expect(customerService.headers.get('location')).toBe('http://127.0.0.1:18011/customer-service.html')
    expect(customerService.headers.get('cache-control')).toBe('no-store')
  } finally {
    await vite?.close()
    if (previousStorefrontOrigin === undefined) delete process.env.SHOP_API_ORIGIN
    else process.env.SHOP_API_ORIGIN = previousStorefrontOrigin
    if (previousCustomerServiceOrigin === undefined) delete process.env.SHOP_CUSTOMER_SERVICE_ORIGIN
    else process.env.SHOP_CUSTOMER_SERVICE_ORIGIN = previousCustomerServiceOrigin
    if (previousCustomerServiceMode === undefined) delete process.env.SHOP_CUSTOMER_SERVICE_MODE
    else process.env.SHOP_CUSTOMER_SERVICE_MODE = previousCustomerServiceMode
  }
})
