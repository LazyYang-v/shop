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
    const freeText = page.waitForResponse(r => new URL(r.url()).pathname === '/api/customer-service/messages')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    assert.equal((await freeText).status(), 200)
    await page.locator('#messages .bubble', { hasText: '请提供完整演示商品名称，并询问价格或库存' }).last().waitFor()
    assert.equal(queries, 1)
    if (process.env.SHOP_DEMO_ORDER_FIXTURE_FILE) {
      const orders = JSON.parse(await readFile(process.env.SHOP_DEMO_ORDER_FIXTURE_FILE, 'utf8'))
      const expected = email === 'buyer-one@customer-service.example'
        ? orders.buyer_one_orders : orders.buyer_two_orders
      const listing = page.waitForResponse(r => new URL(r.url()).pathname === '/api/customer-service/messages')
      await page.locator('#query-orders').click()
      assert.equal((await listing).status(), 200)
      const selection = page.locator('#messages button', { hasText: '的详情' })
      await selection.first().waitFor()
      assert.equal(await selection.count(), expected.length)
      assert.ok(!(await page.locator('#messages').innerText()).includes('不包含实时轨迹或预计送达时间'))
      const details = []
      for (let index = 0; index < expected.length; index++) {
        const detail = page.waitForResponse(r => new URL(r.url()).pathname === '/api/customer-service/messages')
        await selection.nth(index).click()
        assert.equal((await detail).status(), 200)
        const body = await page.locator('#messages').innerText()
        assert.ok(body.includes('不包含实时轨迹或预计送达时间'))
        details.push(body)
      }
      const combined = details.join('\n')
      assert.ok(!combined.includes('演示路') && !combined.includes('13800138000'))
      if (email.startsWith('buyer-one')) {
        assert.ok(combined.includes('虚构速运') && combined.includes('DEMO-ORDERS-001'))
      } else {
        assert.ok(combined.includes('暂无已保存物流信息'))
      }
    }
    if (process.env.SHOP_DEMO_SCREENSHOT) {
      await page.screenshot({ path: process.env.SHOP_DEMO_SCREENSHOT, fullPage: true })
    }
    await context.close()
  }
  const anonymous = await browser.newContext()
  assert.equal((await anonymous.request.get(`${origin}/api/customer-service/products`)).status(), 401)
  await anonymous.close()
  console.log('Demo browser acceptance passed: both buyers, admin/anonymous rejection, fixture/API facts, registration, list/detail/consultation, order selection, controlled free-text clarification, mobile viewport.')
} finally {
  await browser.close()
}
