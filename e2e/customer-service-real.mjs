import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'

const origin = process.env.SHOP_BROWSER_TEST_ORIGIN
assert.ok(/^http:\/\/127\.0\.0\.1:\d+$/.test(origin ?? ''))
const email = process.env.SHOP_BROWSER_TEST_EMAIL
const email2 = process.env.SHOP_BROWSER_TEST_EMAIL_2
const password = process.env.SHOP_BROWSER_TEST_PASSWORD
const orderId = process.env.SHOP_BROWSER_TEST_ORDER_ID
const cancelOrderId = process.env.SHOP_BROWSER_TEST_CANCEL_ORDER_ID
assert.ok(email && email2 && password && /^[0-9a-f-]{36}$/.test(orderId ?? '')
  && /^[0-9a-f-]{36}$/.test(cancelOrderId ?? ''))
const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' })
try {
  for (const [label, viewport] of [['desktop', { width: 1440, height: 1000 }], ['mobile', { width: 390, height: 844 }]]) {
    const context = await browser.newContext({ viewport })
    const page = await context.newPage()
    await page.goto(`${origin}/customer-service.html`)
    const log = page.getByRole('log')
    async function ask(question) {
      await page.getByLabel('请输入想咨询的问题').fill(question)
      const pending = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/messages'))
      await page.getByRole('button', { name: '发送', exact: true }).click()
      const response = await pending
      assert.equal(response.status(), 200)
      return { result: await response.json(), binding: response.request().postDataJSON() }
    }
    const listing = await ask('请问有哪些商品？')
    const expected = { id: '00000000-0000-0000-0000-000000000001', name: '春日轻盈针织开衫', category: '女装', price: '129.00', stock: 24, is_listed: true }
    assert.deepEqual(listing.result.data.cards.map(card => card.product).find(product => product.id === expected.id), expected)
    const compound = await ask('请问春日轻盈针织开衫的价格和库存？')
    assert.equal(compound.result.status, 'ok')
    assert.deepEqual(compound.result.data.cards[0].product, expected)
    await page.waitForFunction(id => document.querySelector('[role="log"]').textContent.includes(id), compound.result.request_id)
    assert.ok((await log.textContent()).includes(compound.result.request_id))
    assert.ok((await log.textContent()).includes(compound.result.queried_at))
    const policy = await ask('演示商城多久发货？')
    assert.equal(policy.result.status, 'ok')
    assert.equal(policy.result.data.synthetic, true)
    assert.equal(policy.result.data.citations.length, 1)
    assert.equal(policy.result.data.citations[0].version, 2)
    assert.equal(policy.result.data.citations[0].source_ref, 'synthetic://policies/demo-shipping-v2')
    await page.waitForFunction(() => document.querySelector('[role="log"]').textContent.includes('版本：v2'))
    assert.ok((await log.textContent()).includes('虚构演示政策（非真实商城政策）'))
    assert.ok(!(await log.textContent()).includes('PRIVATE_POLICY_SENTINEL'))
    assert.ok(!(await log.textContent()).includes('PRIVATE_RESEARCH_SENTINEL'))
    const noMatch = await ask('演示商城礼品包装政策是什么？')
    assert.equal(noMatch.result.status, 'empty')
    assert.equal(noMatch.result.code, 'policy_no_match')
    assert.deepEqual(noMatch.result.data.citations, [])
    await page.waitForFunction(() => document.querySelector('[role="log"]').textContent.includes('非商城政策'))
    assert.ok(!(await log.textContent()).includes('PRIVATE_RESEARCH_SENTINEL'))
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    await page.screenshot({ path: `/tmp/shop-phase-b-${label}.png`, fullPage: true })
    const unknown = await ask('PRIVATE_SENTINEL，春日轻盈针织开衫多少钱？')
    assert.equal(unknown.result.status, 'needs_clarification')
    assert.deepEqual(unknown.result.data.cards, [])
    const other = await browser.newContext()
    const csrf = (await (await other.request.get(`${origin}/api/auth/csrf`)).json()).csrf_token
    assert.equal((await other.request.post(`${origin}/api/customer-service/messages`, {
      headers: { Origin: origin, 'X-CSRF-Token': csrf }, data: { ...compound.binding, client_message_id: crypto.randomUUID() },
    })).status(), 403)
    assert.equal((await context.request.get(`${origin}/api/orders`)).status(), 401)
    await other.close()
    await context.close()
  }
  async function login(page, account) {
    await page.goto(`${origin}/customer-service.html`)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await page.getByLabel('邮箱').fill(account)
    await page.getByLabel('密码').fill(password)
    await Promise.all([page.waitForNavigation(), page.locator('#login-submit').click()])
    await page.waitForFunction(() => document.getElementById('account-status').textContent === '已登录买家')
  }
  async function logout(page) {
    await Promise.all([page.waitForNavigation(), page.getByRole('button', { name: '退出', exact: true }).click()])
    await page.waitForFunction(() => document.getElementById('account-status').textContent.includes('未登录'))
  }
  const ownerContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const ownerPage = await ownerContext.newPage()
  await login(ownerPage, email)
  const ownerLog = ownerPage.getByRole('log')
  let pending = ownerPage.waitForResponse(response => new URL(response.url()).pathname.endsWith('/messages'))
  await ownerPage.getByRole('button', { name: '查询我的订单' }).click()
  let response = await pending
  assert.equal(response.status(), 200)
  const listing = await response.json()
  assert.equal(listing.status, 'ok')
  assert.equal(listing.data.cards.length, 2)
  assert.deepEqual(listing.data.cards.map(card => card.order.order_number).sort(), [orderId, cancelOrderId].sort())
  for (const card of listing.data.cards) {
    assert.deepEqual(Object.keys(card.order).sort(), ['created_at', 'order_number', 'product_summary', 'status', 'total'])
    assert.equal(card.order.total, '129.00')
  }
  assert.equal(response.request().postDataJSON().text, '查询我的订单')
  assert.equal('selected_order_id' in response.request().postDataJSON(), false)
  await ownerPage.waitForFunction(id => document.querySelector('[role="log"]').textContent.includes(id), orderId)
  pending = ownerPage.waitForResponse(item => new URL(item.url()).pathname.endsWith('/messages'))
  await ownerPage.getByRole('button', { name: `查询订单 ${orderId.slice(0, 8)}… 的详情` }).click()
  response = await pending
  assert.equal(response.status(), 200)
  const detail = await response.json()
  assert.equal(detail.data.cards[0].type, 'order_detail')
  assert.equal(detail.data.cards[0].order.order_number, orderId)
  assert.equal(detail.data.cards[0].order.tracking_number, 'DEMO-BROWSER-001')
  assert.equal(response.request().postDataJSON().selected_order_id, orderId)
  assert.equal('text' in response.request().postDataJSON(), false)
  await ownerPage.waitForFunction(() => document.querySelector('[role="log"]').textContent.includes('DEMO-BROWSER-001'))
  let text = await ownerLog.textContent()
  assert.ok(text.includes('以上仅为商城已保存的物流信息，不包含实时轨迹或预计送达时间。'))
  for (const forbidden of ['PRIVATE_PHONE_SENTINEL', 'PRIVATE_ADDRESS_SENTINEL', '13800138000', '文三路']) {
    assert.ok(!text.includes(forbidden))
  }

  pending = ownerPage.waitForResponse(item => new URL(item.url()).pathname.endsWith('/messages'))
  await ownerPage.getByRole('button', { name: `查询订单 ${cancelOrderId.slice(0, 8)}… 的详情` }).click()
  response = await pending
  assert.equal(response.status(), 200)
  const cancelDetail = await response.json()
  assert.equal(cancelDetail.data.cards[0].type, 'order_detail')
  assert.equal(cancelDetail.data.cards[0].order.order_number, cancelOrderId)
  assert.equal(cancelDetail.data.cards[0].order.status, 'pending_payment')
  assert.equal(response.request().postDataJSON().selected_order_id, cancelOrderId)
  const cancelRequest = ownerPage.getByRole('button', { name: '申请取消订单' })
  assert.equal(await cancelRequest.count(), 1)
  pending = ownerPage.waitForResponse(item => new URL(item.url()).pathname.endsWith('/messages'))
  await cancelRequest.click()
  response = await pending
  assert.equal(response.status(), 200)
  const proposal = await response.json()
  const card = proposal.confirmation_card
  assert.equal(proposal.status, 'ok')
  assert.deepEqual(proposal.data.cards, [])
  assert.deepEqual(Object.keys(card).sort(), ['confirmation_token', 'currency', 'expires_at', 'operation_id',
    'order_number', 'product_summary', 'status', 'total'])
  assert.equal(card.order_number, cancelOrderId)
  assert.equal(card.status, 'pending_payment')
  assert.equal(card.total, '129.00')
  assert.equal(card.currency, 'CNY')
  assert.match(card.operation_id, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/)
  assert.notEqual(card.operation_id, cancelOrderId)
  assert.match(card.confirmation_token, /^[A-Za-z0-9_-]{43}$/)
  assert.ok(Date.parse(card.expires_at) > Date.now())
  assert.ok(Date.parse(card.expires_at) <= Date.now() + 120000)
  assert.equal(response.request().postDataJSON().text, '申请取消订单')
  assert.equal(response.request().postDataJSON().selected_order_id, cancelOrderId)
  const chatPayload = JSON.stringify({ data: proposal.data, code: proposal.code, message: proposal.message })
  assert.ok(!chatPayload.includes(card.confirmation_token))
  assert.ok(!chatPayload.includes(card.operation_id))

  const confirmationCard = ownerPage.locator('.confirmation-card')
  await confirmationCard.waitFor()
  const cardText = await confirmationCard.textContent()
  for (const expected of [`操作编号：${card.operation_id}`, cancelOrderId, '待付款', '¥129.00',
    '取消后将恢复商品库存；操作不可撤销；购物车不会恢复。', '请核对订单与取消后果，再确认取消。']) {
    assert.ok(cardText.includes(expected))
  }
  const confirmButton = confirmationCard.getByRole('button', { name: '确认取消订单' })
  assert.equal(await confirmButton.count(), 1)
  assert.equal(await confirmButton.isEnabled(), true)
  assert.ok(!(await ownerLog.textContent()).includes(card.confirmation_token))
  const storage = await ownerPage.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage } }))
  for (const secret of [card.confirmation_token, card.operation_id]) {
    assert.ok(!JSON.stringify(storage).includes(secret))
    assert.ok(!ownerPage.url().includes(secret))
  }
  assert.ok(!(await ownerPage.content()).includes(card.confirmation_token))
  assert.ok((await ownerPage.content()).includes(card.operation_id))

  const confirmRequest = ownerPage.waitForResponse(item => new URL(item.url()).pathname.endsWith('/cancel/confirm'))
  await confirmButton.click()
  response = await confirmRequest
  assert.equal(response.status(), 200)
  const execution = await response.json()
  assert.equal(execution.status, 'executed')
  assert.equal(execution.data.operation_id, card.operation_id)
  assert.equal(execution.data.order_id, cancelOrderId)
  assert.equal(execution.data.order_status, 'closed')
  assert.equal(execution.data.close_reason, 'buyer_cancelled')
  assert.equal(execution.data.evidence.close_reason, 'buyer_cancelled')
  await ownerPage.waitForFunction(() => document.querySelector('[role="log"]').textContent.includes('取消成功：本人订单已关闭，原因是买家取消。'))
  assert.equal((await ownerLog.textContent()).includes('取消结果待核验'), false)
  assert.equal((await ownerLog.textContent()).includes('已取消订单，商品库存已恢复。'), false)
  assert.ok(!(await ownerLog.textContent()).includes(card.confirmation_token))
  await ownerPage.reload()
  await ownerPage.waitForFunction(() => document.getElementById('account-status').textContent === '已登录买家')
  assert.equal(await ownerPage.locator('.confirmation-card').count(), 0)
  const restored = await ownerPage.evaluate(() => ({ ...sessionStorage }))
  for (const secret of [card.confirmation_token, card.operation_id]) {
    assert.ok(!JSON.stringify(restored).includes(secret))
  }
  assert.notEqual(restored['shop.customer-service.handoff'], card.confirmation_token)
  pending = ownerPage.waitForResponse(item => new URL(item.url()).pathname.endsWith('/messages'))
  await ownerPage.getByRole('button', { name: '查询我的订单' }).click()
  response = await pending
  assert.equal(response.status(), 200)
  const afterHandoff = await response.json()
  assert.equal(afterHandoff.data.cards.length, 2)
  assert.equal('confirmation_card' in afterHandoff, false)

  await logout(ownerPage)
  pending = ownerPage.waitForResponse(item => new URL(item.url()).pathname.endsWith('/messages'))
  await ownerPage.getByRole('button', { name: '查询我的订单' }).click()
  response = await pending
  assert.equal(response.status(), 401)
  await ownerPage.getByRole('dialog', { name: '登录后查看本人订单' }).waitFor()
  await ownerPage.waitForFunction(() => document.querySelector('[role="log"]').textContent.includes('请登录后查看本人订单。'))
  await login(ownerPage, email2)
  pending = ownerPage.waitForResponse(item => new URL(item.url()).pathname.endsWith('/messages'))
  await ownerPage.getByRole('button', { name: '查询我的订单' }).click()
  response = await pending
  assert.equal(response.status(), 200)
  const empty = await response.json()
  assert.equal(empty.status, 'empty')
  assert.equal(empty.data.reply, '未找到可访问订单')
  assert.deepEqual(empty.data.cards, [])
  text = await ownerPage.getByRole('log').textContent()
  assert.ok(!text.includes(orderId))
  await ownerContext.close()
  console.log('Chrome desktop/mobile anonymous sentences -> messages -> local MCP -> real fixture DB -> synthetic exchange + real ledger passed; unknown private text clarifies, cross-session pages denied. Real provider calls=0, money=0.')
} finally {
  await browser.close()
}
