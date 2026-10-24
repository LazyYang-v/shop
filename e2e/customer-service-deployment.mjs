import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { chromium } from '@playwright/test'

const origin = process.env.SHOP_DEMO_ORIGIN
const mode = process.env.SHOP_DEMO_ACCEPTANCE_MODE ?? 'deployment'
const artifactDirectory = process.env.SHOP_DEMO_ARTIFACT_DIRECTORY
assert.ok(['deployment', 'recovery', 'outage'].includes(mode))
assert.ok(/^http:\/\/127\.0\.0\.1:(18011|18013)$/.test(origin ?? ''))
assert.ok(path.isAbsolute(artifactDirectory ?? ''))
await mkdir(artifactDirectory, { recursive: true, mode: 0o700 })
assert.equal((await stat(artifactDirectory)).mode & 0o077, 0)
const passwordPath = process.env.SHOP_DEMO_PASSWORD_FILE
assert.equal((await stat(passwordPath)).mode & 0o077, 0)
const passwords = JSON.parse(await readFile(passwordPath, 'utf8'))
const fixture = JSON.parse(await readFile(new URL('../deploy/customer-service-demo/products.v1.json', import.meta.url), 'utf8'))
const emails = ['buyer-one@customer-service.example', 'buyer-two@customer-service.example']
const adminEmail = 'admin@customer-service.example'
const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' })
const errors = []
let assertions = 0

async function savePrivate(filename, value) {
  await writeFile(path.join(artifactDirectory, filename), JSON.stringify(value, null, 2), { flag: 'wx', mode: 0o600 })
}
async function csrf(context) {
  const response = await context.request.get(`${origin}/api/auth/csrf`)
  assert.equal(response.status(), 200)
  return { Origin: origin, 'X-CSRF-Token': (await response.json()).csrf_token }
}
async function post(context, route, data, status = 200, extraHeaders = {}) {
  const response = await context.request.post(origin + route, { headers: { ...await csrf(context), ...extraHeaders }, data })
  assert.equal(response.status(), status, `Unexpected status for ${route}`)
  assertions++
  return response.json()
}
async function account(email) {
  const context = await browser.newContext()
  await post(context, '/api/auth/login', { email, password: passwords[email] })
  return context
}
async function loginPage(context, email) {
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.name))
  await page.goto(`${origin}/customer-service.html`)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByLabel('邮箱').fill(email)
  await page.getByLabel('密码').fill(passwords[email])
  await Promise.all([page.waitForNavigation(), page.locator('#login-submit').click()])
  await page.waitForFunction(() => document.getElementById('account-status').textContent === '已登录买家')
  return page
}
async function ask(page, text, selectedOrderId) {
  let response
  if (selectedOrderId) {
    const pending = page.waitForResponse(item => new URL(item.url()).pathname.endsWith('/messages'))
    await page.getByRole('button', { name: `查询订单 ${selectedOrderId.slice(0, 8)}… 的详情` }).last().click()
    response = await pending
  } else {
    await page.getByLabel('请输入想咨询的问题').fill(text)
    const pending = page.waitForResponse(item => new URL(item.url()).pathname.endsWith('/messages'))
    await page.getByRole('button', { name: '发送', exact: true }).click()
    response = await pending
  }
  assert.equal(response.status(), 200)
  assertions++
  return { result: await response.json(), binding: response.request().postDataJSON() }
}
async function products(context) {
  const response = await context.request.get(`${origin}/api/customer-service/products`)
  assert.equal(response.status(), 200)
  const items = (await response.json()).data.items
  assert.equal(items.length, fixture.length)
  for (const expected of fixture) assert.deepEqual(items.find(item => item.id === expected.id), expected)
  assertions++
}
async function order(context, id) {
  const response = await context.request.get(`${origin}/api/orders/${id}`)
  assert.equal(response.status(), 200)
  return response.json()
}

try {
  if (mode === 'deployment') {
    const anonymous = await browser.newContext()
    await csrf(anonymous)
    await products(anonymous)
    const anonymousPage = await anonymous.newPage()
    await anonymousPage.goto(`${origin}/customer-service.html`)
    assert.equal((await ask(anonymousPage, '演示商城多久发货？')).result.status, 'ok')
    assert.equal((await ask(anonymousPage, 'PRIVATE_DEPLOYMENT_SENTINEL，帮我退款')).result.status, 'needs_clarification')
    assert.equal((await anonymous.request.get(`${origin}/api/orders`)).status(), 401)
    await anonymous.close()
    const admin = await account(adminEmail)
    assert.equal((await admin.request.get(`${origin}/api/customer-service/products`)).status(), 403)
    const createdProduct = await post(admin, '/api/admin/products', {
      name: '演示部署验收专用商品（虚构）', category: '演示', description: '仅供隔离部署创建虚构订单，不加入客服商品白名单。',
      image_url: '/images/demo-deployment.png', price: '1.00', is_listed: true,
    }, 201)
    await post(admin, `/api/admin/products/${createdProduct.id}/inventory-adjustments`, { delta: 4, reason: '隔离部署验收初始虚构库存' }, 201)
    const prepared = []
    for (const [index, email] of emails.entries()) {
      const context = await account(email)
      const cart = await (await context.request.get(`${origin}/api/cart`)).json()
      assert.deepEqual(cart.items, [])
      const address = await post(context, '/api/addresses', {
        recipient_name: '虚构演示买家', phone: '13800138000', province: '演示省', city: '演示市', district: '演示区', detail: '演示路 9 号',
      }, 201)
      async function createOrder() {
        await post(context, '/api/cart/items', { product_id: createdProduct.id, quantity: 1 }, 201)
        return post(context, '/api/orders', { address_id: address.id }, 201, { 'Idempotency-Key': randomUUID() })
      }
      const receipt = await createOrder()
      await post(context, `/api/orders/${receipt.id}/pay`, {})
      const tracking = `DEMO-T9-${index + 1}-001`
      await post(admin, `/api/admin/orders/${receipt.id}/ship`, { shipping_company: '虚构速运', tracking_number: tracking })
      const pending = await createOrder()
      prepared.push({ email, receiptId: receipt.id, pendingId: pending.id, tracking })
      await context.close()
    }
    await savePrivate('prepared-orders.json', { prepared, productId: createdProduct.id })
    const recoveryInputs = []
    for (const [index, data] of prepared.entries()) {
      const label = index === 0 ? 'desktop' : 'mobile'
      const context = await browser.newContext({ viewport: index === 0 ? { width: 1440, height: 1000 } : { width: 390, height: 844 } })
      const page = await loginPage(context, data.email)
      await products(context)
      const listed = await ask(page, '查询我的订单')
      assert.ok(listed.result.data.cards.every(card => card.type === 'order'))
      await ask(page, null, data.receiptId)
      const delivery = (await ask(page, index === 0 ? '快递未到且想退款' : '快递未到，我想退款')).result
      assert.equal(delivery.status, 'ok')
      assert.equal(delivery.data.cards[0].order.tracking_number, data.tracking)
      assert.equal('confirmation_card' in delivery, false)
      for (const text of ['没有退款接口', '未办理退款', '不提供实时轨迹或预计送达时间', '不符合未支付订单取消条件']) assert.ok(delivery.data.reply.includes(text))
      const combined = (await ask(page, '演示商城多久发货？；查询我的订单')).result
      assert.equal(combined.status, 'ok')
      assert.ok(combined.data.parts.some(part => part.source === 'get_my_order' && part.status === 'ok'))
      assert.ok(combined.data.parts.some(part => part.source === 'search_policy' && part.status === 'ok'))
      assert.equal(combined.data.citations[0].source_ref, 'synthetic://policies/demo-shipping-v2')
      await ask(page, null, data.pendingId)
      const proposed = await ask(page, '快递未到且想退款')
      const card = proposed.result.confirmation_card
      assert.equal(card.order_number, data.pendingId)
      assert.equal((await order(context, data.pendingId)).status, 'pending_payment')
      const beforeStock = (await (await admin.request.get(`${origin}/api/admin/products/${createdProduct.id}`)).json()).stock
      let confirmations = 0
      await page.route('**/api/customer-service/cancel/confirm', async route => {
        confirmations++
        const committed = await route.fetch()
        assert.equal(committed.status(), 200)
        assert.equal((await committed.json()).status, 'executed')
        await route.abort('connectionreset')
      })
      const reconciliation = page.waitForResponse(item => new URL(item.url()).pathname.endsWith('/cancel/reconcile'))
      await page.locator('.confirmation-card').last().getByRole('button', { name: '确认取消订单', exact: true }).click()
      const reconciled = await (await reconciliation).json()
      assert.equal(reconciled.status, 'executed')
      assert.equal(reconciled.data.operation_id, card.operation_id)
      assert.equal(confirmations, 1)
      await page.waitForFunction(() => document.querySelector('[role="log"]').textContent.includes('取消成功：本人订单已关闭，原因是买家取消。'))
      assert.equal(await page.locator('.confirmation-card').last().locator('.invalid-note').textContent(), '本次取消已由商城订单与操作证据确认。')
      const body = await page.getByRole('log').innerText()
      assert.ok(!body.includes('响应未能确认；页面不会重发取消。'))
      assert.ok(!body.includes('取消请求仍在处理中；页面不会重发取消。'))
      assert.ok(!body.includes('13800138000') && !body.includes('演示路 9 号'))
      assert.equal((await order(context, data.pendingId)).close_reason, 'buyer_cancelled')
      const stock = (await (await admin.request.get(`${origin}/api/admin/products/${createdProduct.id}`)).json()).stock
      assert.equal(stock, beforeStock + 1)
      const binding = { page_instance_id: proposed.binding.page_instance_id, consultation_id: proposed.binding.consultation_id, operation_id: card.operation_id }
      const repeated = await post(context, '/api/customer-service/cancel/reconcile', binding)
      assert.deepEqual(repeated.data.evidence, reconciled.data.evidence)
      const other = await account(emails[1 - index])
      assert.equal((await other.request.get(`${origin}/api/orders/${data.pendingId}`)).status(), 404)
      await post(other, '/api/customer-service/cancel/reconcile', binding, 403)
      await other.close()
      const storage = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }))
      assert.ok(!storage.includes(card.confirmation_token) && !(await page.content()).includes(card.confirmation_token))
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      await page.screenshot({ path: path.join(artifactDirectory, `ticket-9-deployment-${label}.png`), fullPage: true })
      recoveryInputs.push({ email: data.email, storageState: await context.storageState(), binding: proposed.binding, orderId: data.pendingId })
      await context.close()
    }
    await savePrivate('recovery-inputs.json', recoveryInputs)
    const buyer = await account(emails[0])
    await products(buyer)
    await buyer.close()
    await admin.close()
  } else if (mode === 'outage') {
    const prepared = JSON.parse(await readFile(process.env.SHOP_DEMO_PREPARED_ORDERS_FILE, 'utf8')).prepared
    for (const [index, data] of prepared.entries()) {
      const context = await browser.newContext({ viewport: index === 0 ? { width: 1440, height: 1000 } : { width: 390, height: 844 } })
      const page = await loginPage(context, data.email)
      await ask(page, '查询我的订单')
      await ask(page, null, data.receiptId)
      const partial = (await ask(page, '演示商城多久发货？；查询我的订单')).result
      assert.equal(partial.status, 'partial')
      assert.equal(partial.code, 'policy_unavailable')
      assert.equal(partial.data.cards[0].order.order_number, data.receiptId)
      assert.deepEqual(partial.data.citations, [])
      assert.equal((await ask(page, '查询我的订单')).result.status, 'ok')
      await page.screenshot({ path: path.join(artifactDirectory, `ticket-9-outage-${index === 0 ? 'desktop' : 'mobile'}.png`), fullPage: true })
      await context.close()
    }
  } else {
    const oldInputs = JSON.parse(await readFile(process.env.SHOP_DEMO_PREVIOUS_SESSION_FILE, 'utf8'))
    const oldPasswords = JSON.parse(await readFile(process.env.SHOP_DEMO_PREVIOUS_PASSWORD_FILE, 'utf8'))
    for (const [index, input] of oldInputs.entries()) {
      const previous = await browser.newContext({ storageState: input.storageState })
      assert.equal((await previous.request.get(`${origin}/api/orders`)).status(), 401)
      await previous.close()
      const oldPassword = await browser.newContext()
      await post(oldPassword, '/api/auth/login', { email: input.email, password: oldPasswords[input.email] }, 401)
      await oldPassword.close()
      const context = await browser.newContext({ viewport: index === 0 ? { width: 1440, height: 1000 } : { width: 390, height: 844 } })
      const page = await loginPage(context, input.email)
      await products(context)
      const existing = await (await context.request.get(`${origin}/api/orders`)).json()
      assert.equal(existing.total, 0)
      assert.equal((await context.request.get(`${origin}/api/orders/${input.orderId}`)).status(), 404)
      const oldBinding = { ...input.binding, client_message_id: randomUUID() }
      await post(context, '/api/customer-service/messages', oldBinding, 410)
      assert.equal((await ask(page, '请问有哪些商品？')).result.status, 'ok')
      const policy = (await ask(page, '演示商城多久发货？')).result
      assert.equal(policy.status, 'ok')
      assert.equal(policy.data.citations[0].version, 2)
      assert.ok((await page.getByRole('log').textContent()).includes('虚构演示政策（非真实商城政策）'))
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      await page.screenshot({ path: path.join(artifactDirectory, `ticket-9-recovery-${index === 0 ? 'desktop' : 'mobile'}.png`), fullPage: true })
      await context.close()
    }
  }
  assert.deepEqual(errors, [])
  const report = { mode, origin, assertions, desktop: 'passed', mobile: 'passed', browser_page_errors: errors.length, paid_calls: 0, weknora_calls: 0, finished_utc: new Date().toISOString() }
  await savePrivate(`${mode}-acceptance.json`, report)
  console.log(JSON.stringify(report))
} finally {
  await browser.close()
}
