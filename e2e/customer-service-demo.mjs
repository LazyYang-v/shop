import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { chromium } from '@playwright/test'

const origin = process.env.SHOP_DEMO_ORIGIN
assert.ok(/^http:\/\/127\.0\.0\.1:\d+$/.test(origin ?? ''))
const passwords = JSON.parse(await readFile(process.env.SHOP_DEMO_PASSWORD_FILE, 'utf8'))
const fixture = JSON.parse(await readFile(new URL('../deploy/customer-service-demo/products.v1.json', import.meta.url), 'utf8'))
const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' })
try {
  for (const email of ['buyer-one@customer-service.example', 'buyer-two@customer-service.example', 'admin@customer-service.example']) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
    const csrf = (await (await context.request.get(`${origin}/api/auth/csrf`)).json()).csrf_token
    const headers = { Origin: origin, 'X-CSRF-Token': csrf }
    const registered = await context.request.post(`${origin}/api/auth/register`, {
      headers, data: { email: 'unapproved@example.com', password: 'fictional-unapproved-password' },
    })
    assert.equal(registered.status(), 403)
    const login = await context.request.post(`${origin}/api/auth/login`, { headers, data: { email, password: passwords[email] } })
    assert.equal(login.status(), 200)
    const listing = await context.request.get(`${origin}/api/customer-service/products`)
    if (email.startsWith('admin')) {
      assert.equal(listing.status(), 403)
      await context.close()
      continue
    }
    assert.equal(listing.status(), 200)
    const result = await listing.json()
    assert.equal(result.data.items.length, fixture.length)
    for (const product of fixture) {
      const found = result.data.items.find(item => item.id === product.id)
      for (const field of ['name', 'category', 'price', 'stock', 'is_listed']) assert.equal(found[field], product[field])
      const detail = await context.request.get(`${origin}/api/products/${product.id}`)
      assert.equal(detail.status(), 200)
      const business = await detail.json()
      for (const field of ['name', 'category', 'price', 'stock']) assert.equal(business[field], found[field])
      // The ordinary detail route serves listed products and omits is_listed.
      assert.equal(found.is_listed, true)
    }
    assert.equal((await context.request.get(`${origin}/api/customer-service/products?unknown=1`)).status(), 422)
    assert.equal((await context.request.get(`${origin}/api/customer-service/products/00000000-0000-4000-8000-999999999999`)).status(), 403)
    const empty = await context.request.get(`${origin}/api/customer-service/products?q=missing-sentinel`)
    assert.equal(empty.status(), 200)
    assert.equal((await empty.json()).status, 'empty')
    const page = await context.newPage()
    await page.goto(`${origin}/customer-service.html`)
    const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/customer-service/products')
    await page.getByRole('button', { name: '查看演示商品', exact: true }).click()
    assert.equal((await response).status(), 200)
    const first = fixture[0]
    const detailResponse = page.waitForResponse(r => new URL(r.url()).pathname === `/api/customer-service/products/${first.id}`)
    await page.getByRole('button', { name: `查询 ${first.name} 的最新价格与库存` }).click()
    assert.equal((await detailResponse).status(), 200)
    const message = page.waitForResponse(r => new URL(r.url()).pathname === '/api/customer-service/messages')
    await page.getByRole('button', { name: '开始商品咨询', exact: true }).click()
    assert.equal((await message).status(), 200)
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    let queries = 0
    page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/customer-service/')) queries++ })
    await page.getByLabel('请输入想咨询的问题').fill('LOG-SENTINEL-private-body-do-not-store')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.getByText('亲，商品客服功能尚未开放。您可以先在商城商品目录中查询商品信息。', { exact: true }).waitFor()
    assert.equal(queries, 0)
    if (process.env.SHOP_DEMO_SCREENSHOT) {
      await page.screenshot({ path: process.env.SHOP_DEMO_SCREENSHOT, fullPage: true })
    }
    await context.close()
  }
  const anonymous = await browser.newContext()
  assert.equal((await anonymous.request.get(`${origin}/api/customer-service/products`)).status(), 401)
  await anonymous.close()
  console.log('Demo browser acceptance passed: both buyers, admin/anonymous rejection, fixture/API facts, registration, list/detail/consultation, mobile and free-text isolation.')
} finally {
  await browser.close()
}
