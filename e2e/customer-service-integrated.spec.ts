import { expect, test } from '@playwright/test'

const product = {
  id: '00000000-0000-4000-8000-000000000001', name: '商城商品',
  category: '办公', price: '129.00', stock: 24, is_listed: true,
}
const orderNumber = '00000000-0000-4000-8000-000000000002'
const operationId = '00000000-0000-4000-8000-000000000003'

function envelope(data: Record<string, unknown>, extra = {}) {
  return {
    request_id: '00000000-0000-4000-8000-000000000004',
    queried_at: new Date().toISOString(), status: 'ok', data, ...extra,
  }
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({ json: {
    id: '00000000-0000-4000-8000-000000000005', role: 'buyer',
  } }))
  await page.route('**/api/auth/csrf', route => route.fulfill({ json: { csrf_token: 'synthetic-csrf' } }))
  await page.route('**/api/customer-service/mode', route => route.fulfill({ json: { mode: 'integrated', enabled: true } }))
  await page.route('**/api/customer-service/pages', route => route.fulfill({ status: 201, json: envelope({
    page_instance_id: '00000000-0000-4000-8000-000000000006',
    consultation_id: '00000000-0000-4000-8000-000000000007', handoff_token: 'a'.repeat(43),
  }) }))
})

test('storefront login returns to customer service with the same account', async ({ page }) => {
  let signedIn = false
  const user = { id: '00000000-0000-4000-8000-000000000005', email: 'synthetic-buyer@example.com', role: 'buyer' }
  await page.route('**/api/auth/me', route => signedIn
    ? route.fulfill({ json: user })
    : route.fulfill({ status: 401, json: { detail: '需要登录' } }))
  await page.route('**/api/auth/login', async route => {
    signedIn = true
    await route.fulfill({ json: { user } })
  })
  await page.goto('/customer-service.html')
  await page.locator('.account-menu > summary').click()
  await page.getByRole('link', { name: '前往商城登录后继续' }).click()
  await expect(page).toHaveURL(/customer-service-return=1/)
  await page.getByLabel('邮箱', { exact: true }).fill(user.email)
  await page.getByLabel('密码', { exact: true }).fill('synthetic-password-123')
  await page.getByRole('dialog').getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/customer-service\.html$/)
  await expect(page.locator('#account-label')).toHaveText('商城买家')
  await expect(page.locator('input[type="password"]')).toHaveCount(0)
})

test('integrated cancellation shows the confirmation card and sends only the buyer click', async ({ page }) => {
  let confirmations = 0
  await page.route('**/api/customer-service/messages', route => route.fulfill({ json: envelope({
    reply: '已生成取消确认方案。', cards: [], citations: [],
  }, { confirmation_card: {
    operation_id: operationId, order_number: orderNumber, product_summary: '商城商品 ×1',
    status: 'pending_payment', total: '129.00', currency: 'CNY',
    expires_at: new Date(Date.now() + 120_000).toISOString(), confirmation_token: 'b'.repeat(43),
  } }) }))
  await page.route('**/api/customer-service/cancel/confirm', async route => {
    confirmations += 1
    expect(route.request().postDataJSON()).toMatchObject({
      operation_id: operationId, confirmation_token: 'b'.repeat(43),
    })
    await route.fulfill({ json: envelope({}, { status: 'rejected' }) })
  })
  await page.goto('/customer-service.html')
  await page.getByLabel('请输入想咨询的问题').fill('申请取消订单')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const confirm = page.getByRole('button', { name: '确认取消订单', exact: true })
  await expect(confirm).toBeVisible()
  expect(confirmations).toBe(0)
  await expect(page.getByRole('log')).not.toContainText('b'.repeat(43))
  expect(await page.evaluate(() => JSON.stringify({ ...sessionStorage, ...localStorage }))).not.toContain('b'.repeat(43))
  await confirm.click()
  await expect(page.getByRole('log')).toContainText('取消未执行')
  expect(confirmations).toBe(1)
})

test('product pagination keeps the search keyword', async ({ page }) => {
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/customer-service/messages', async route => {
    requests.push(route.request().postDataJSON())
    await route.fulfill({ json: envelope({ reply: '匹配到商城商品。', citations: [], cards: requests.length === 1 ? [
      { type: 'product', product, selection_text: `查看商品：${product.id}` },
      { type: 'product_page', selection_text: '查看商品第2页：办公' },
    ] : [] }) })
  })
  await page.goto('/customer-service.html')
  await page.getByLabel('请输入想咨询的问题').fill('办公')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await page.getByRole('button', { name: '下一页商城商品', exact: true }).click()
  await expect.poll(() => requests.length).toBe(2)
  expect(requests[1].text).toBe('查看商品第2页：办公')
})

test('order pagination lets the buyer find older candidates', async ({ page }) => {
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/customer-service/messages', async route => {
    requests.push(route.request().postDataJSON())
    await route.fulfill({ json: envelope({ reply: '请选择一笔订单。', citations: [], cards: requests.length === 1 ? [
      { type: 'order_page', selection_text: '查询我的订单第2页' },
    ] : [] }) })
  })
  await page.goto('/customer-service.html')
  await page.getByRole('button', { name: '我的订单', exact: true }).click()
  await page.getByRole('button', { name: '下一页本人订单', exact: true }).click()
  await expect.poll(() => requests.length).toBe(2)
  expect(requests[1].text).toBe('查询我的订单第2页')
})

test('size advice submits explicit measurements into the active consultation', async ({ page }) => {
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/customer-service/messages', async route => {
    requests.push(route.request().postDataJSON())
    await route.fulfill({ json: envelope({ reply: requests.length === 1 ? '请补充尺寸' : '已发布尺码表范围匹配 M', citations: [],
      cards: requests.length === 1 ? [{ type: 'size_advice', product_id: product.id, product_name: product.name, advice: {
        status: 'ok', sizes: [{ label: 'M', measurements: { height_cm: [160, 170], weight_kg: [50, 60] } }],
        recommendations: [], needs: ['请补充身高和体重'], citations: [],
      } }] : [] }) })
  })
  await page.goto('/customer-service.html')
  await page.getByLabel('请输入想咨询的问题').fill('这件商品怎么选尺码')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const advice = page.locator('.support-card').filter({ hasText: '尺码建议' })
  await advice.getByLabel('身高（厘米）').fill('168')
  await advice.getByLabel('体重（公斤）').fill('55')
  await advice.getByRole('button', { name: '按已发布尺码表核对' }).click()
  await expect(page.getByRole('log')).toContainText('范围匹配 M')
  expect(requests[1].text).toContain('身高168厘米，体重55公斤')
  expect(requests[1].consultation_id).toBe(requests[0].consultation_id)
})

test('resolved refund progress shows the distinction from money movement', async ({ page }) => {
  await page.route('**/api/customer-service/messages', route => route.fulfill({ json: envelope({
    reply: '以下是服务申请的工单审核进度。', citations: [], cards: [{ type: 'service_progress', progress: {
      order_id: orderNumber, kind: 'refund', has_more: false, notice: '审核进度不代表退款到账。',
      items: [{ case_id: operationId, kind: 'refund', kind_label: '退款申请', status: 'resolved', updated_at: new Date().toISOString(),
        latest_reply: { role: 'staff', text: '已核实诉求，等待资金系统处理', at: new Date().toISOString() },
        execution_status: 'not_connected', executed_actions: [] }],
    } }],
  }) }))
  await page.goto('/customer-service.html')
  await page.getByLabel('请输入想咨询的问题').fill('退款进度')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const progress = page.locator('.support-card').filter({ hasText: '服务申请进度' })
  await expect(progress).toContainText('退款申请 · 处理结束')
  await expect(progress).toContainText('不代表退款到账')
  await expect(progress).toContainText('等待资金系统处理')
})

test('notification mark-read keeps the clicked action across the async request', async ({ page }) => {
  let reads = 0
  await page.route('**/api/customer-service/notifications', route => route.fulfill({ json: { items: [
    { id: operationId, text: '工单有新回复', created_at: new Date().toISOString(), read: false },
  ] } }))
  await page.route(`**/api/customer-service/notifications/${operationId}/read`, async route => {
    reads += 1
    await route.fulfill({ json: { read: true } })
  })
  await page.goto('/customer-service.html')
  await page.getByRole('button', { name: '服务通知', exact: true }).click()
  const action = page.getByRole('button', { name: '标记已读', exact: true })
  await action.click()
  const read = page.getByRole('button', { name: '已读', exact: true })
  await expect(read).toBeDisabled()
  expect(reads).toBe(1)
})

test('faq hints render published questions and send the full title', async ({ page }) => {
  const longTitle = '这是一个特别长的常见问题标题用于验证截断显示'.repeat(2)
  await page.route('**/api/customer-service/faq-hints', route => route.fulfill({ json: { items: [
    { topic: 'returns', title: '七天无理由退货怎么办理' },
    { topic: 'long', title: longTitle },
  ] } }))
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/customer-service/messages', async route => {
    requests.push(route.request().postDataJSON())
    await route.fulfill({ json: envelope({ reply: '已按知识答复。', citations: [], cards: [] }) })
  })
  await page.goto('/customer-service.html')
  const chips = page.locator('#faq-hints')
  await expect(chips).toContainText('常见问题')
  await chips.getByRole('button', { name: '七天无理由退货怎么办理' }).click()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0].text).toBe('七天无理由退货怎么办理')
  await chips.getByRole('button').nth(1).click()
  await expect.poll(() => requests.length).toBe(2)
  expect(requests[1].text).toBe(longTitle)
})

test('order scenario shortcuts follow the signed-in buyer order states', async ({ page }) => {
  await page.route('**/api/orders?*', route => route.fulfill({ json: { items: [
    { id: orderNumber, status: 'pending_payment' },
    { id: '00000000-0000-4000-8000-00000000000a', status: 'pending_shipment' },
  ], total: 2, page: 1, page_size: 50 } }))
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/customer-service/messages', async route => {
    requests.push(route.request().postDataJSON())
    await route.fulfill({ json: envelope({ reply: '已记录催发货申请。', citations: [], cards: [] }) })
  })
  await page.goto('/customer-service.html')
  const chips = page.locator('#order-hints')
  await expect(chips).toContainText('催发货（1 笔待发货）')
  await expect(chips).toContainText('取消待支付订单（1 笔）')
  await chips.getByRole('button', { name: '催发货（1 笔待发货）' }).click()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0].text).toBe('催发货')
})

test('handoff case offers one service rating that posts feedback once', async ({ page }) => {
  const supportCase = { id: operationId, kind: 'human_handoff', status: 'open', assigned: false,
    order_id: null, expires_at: new Date(Date.now() + 86_400_000).toISOString(),
    summary: { concern: '退款未到账', verified_facts: [], executed_actions: [], blocker: '需要人工核实', history: [] },
    messages: [] }
  await page.route('**/api/customer-service/messages', route => route.fulfill({ json: envelope({
    reply: '已创建人工交接工单，当前等待商城管理员接手。', citations: [],
    cards: [{ type: 'support_case', case: supportCase }] }) }))
  let ratings = 0
  await page.route('**/api/customer-service/feedback', async route => {
    ratings += 1
    expect(route.request().postDataJSON()).toMatchObject({ rating: 5, resolved: true })
    await route.fulfill({ json: { saved: true } })
  })
  await page.goto('/customer-service.html')
  await page.getByLabel('请输入想咨询的问题').fill('我要人工客服')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const score = page.getByRole('button', { name: '转人工已受理，可对本次服务打分' })
  await expect(score).toBeVisible()
  await expect(page.locator('.handoff-card')).toContainText('等待接入')
  await expect(page.locator('#service-state')).toHaveAttribute('data-state', 'WAITING_HUMAN')
  await score.click()
  await page.getByLabel('满意度').selectOption('5')
  await page.getByLabel('我的问题已经解决').check()
  await page.getByRole('button', { name: '提交评价', exact: true }).click()
  await expect(page.getByText('评价已保存，谢谢你的反馈。')).toBeVisible()
  expect(ratings).toBe(1)
})

const orderCandidate = {
  order_number: orderNumber, created_at: new Date().toISOString(),
  product_summary: '商城商品 ×1', total: '129.00', status: 'pending_payment',
}

test('order shortcut keeps the conversation and selects inside the chat', async ({ page }) => {
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/customer-service/messages', async route => {
    requests.push(route.request().postDataJSON())
    await route.fulfill({ json: envelope({ reply: '请选择一笔订单。', citations: [], cards: requests.length === 1 ? [
      { type: 'order', order: orderCandidate },
    ] : [] }) })
  })
  await page.goto('/customer-service.html')
  await page.getByRole('button', { name: '选择订单发给客服', exact: true }).click()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0].text).toBe('查询我的订单')
  await expect(page.getByRole('log')).toContainText(orderNumber)
  await page.getByRole('button', { name: '咨询此订单', exact: true }).click()
  await expect.poll(() => requests.length).toBe(2)
  expect(requests[1].selected_order_id).toBe(orderNumber)
  expect(requests[1].text).toBeUndefined()
  await expect(page).toHaveURL(/\/customer-service\.html$/)
})

test('customer service consumes the order parameter as one explicit selection', async ({ page }) => {
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/customer-service/messages', async route => {
    requests.push(route.request().postDataJSON())
    await route.fulfill({ json: envelope({ reply: '已核对你选择的本人订单。', citations: [], cards: [] }) })
  })
  await page.goto(`/customer-service.html?order=${orderNumber}`)
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0].selected_order_id).toBe(orderNumber)
  expect(requests[0].text).toBeUndefined()
  await expect(page.getByRole('log')).toContainText(`咨询订单 · 尾号 ${orderNumber.slice(-4)}`)
  await expect(page).toHaveURL(/\/customer-service\.html$/)
  await page.reload()
  await expect(page.locator('#account-label')).toHaveText('商城买家')
  await expect(page.locator('.chat')).toHaveAttribute('data-customer-service-mode', 'integrated')
  expect(requests).toHaveLength(1)
})

test('anonymous order parameter waits for login and survives the return', async ({ page }) => {
  let signedIn = false
  const user = { id: '00000000-0000-4000-8000-000000000005', email: 'synthetic-buyer@example.com', role: 'buyer' }
  await page.route('**/api/auth/me', route => signedIn
    ? route.fulfill({ json: user })
    : route.fulfill({ status: 401, json: { detail: '需要登录' } }))
  await page.route('**/api/auth/login', async route => {
    signedIn = true
    await route.fulfill({ json: { user } })
  })
  let consultations = 0
  await page.route('**/api/customer-service/pages', async route => {
    consultations += 1
    await route.fulfill({ status: 201, json: envelope({
      page_instance_id: '00000000-0000-4000-8000-000000000006',
      consultation_id: '00000000-0000-4000-8000-000000000007', handoff_token: 'a'.repeat(43),
    }) })
  })
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/customer-service/messages', async route => {
    requests.push(route.request().postDataJSON())
    await route.fulfill({ json: envelope({ reply: '已核对你选择的本人订单。', citations: [], cards: [] }) })
  })
  await page.goto(`/customer-service.html?order=${orderNumber}`)
  await page.locator('.account-menu > summary').click()
  await expect(page.getByText('未登录商城账号')).toBeVisible()
  const login = page.getByRole('link', { name: '前往商城登录后继续' })
  await expect(login).toHaveAttribute('href', `/?customer-service-return=1&customer-service-order=${orderNumber}`)
  expect(consultations).toBe(0)
  expect(requests).toHaveLength(0)
  await expect(page).toHaveURL(new RegExp(`order=${orderNumber}`))
  await login.click()
  await page.getByLabel('邮箱', { exact: true }).fill(user.email)
  await page.getByLabel('密码', { exact: true }).fill('synthetic-password-123')
  await page.getByRole('dialog').getByRole('button', { name: '登录', exact: true }).click()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0].selected_order_id).toBe(orderNumber)
  expect(consultations).toBe(1)
  await expect(page).toHaveURL(/\/customer-service\.html$/)
})

test('orders page hands the order to customer service explicitly', async ({ page }) => {
  const order = { id: orderNumber, status: 'pending_shipment', total: '129.00',
    created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 3_600_000).toISOString(),
    paid_at: new Date().toISOString(), closed_at: null, shipped_at: null, completed_at: null,
    close_reason: null, shipping_company: null, tracking_number: null,
    items: [{ product_id: product.id, name: '商城商品', image_url: '/images/x.png',
      unit_price: '129.00', quantity: 1, line_total: '129.00' }],
    address: { recipient_name: '买家', phone: '13800138000', province: '浙江省',
      city: '杭州市', district: '滨江区', detail: '合成街道 1 号' } }
  await page.route('**/api/categories', route => route.fulfill({ json: ['办公'] }))
  await page.route('**/api/products?*', route => route.fulfill({ json: { items: [product], total: 1, page: 1, page_size: 20 } }))
  await page.route('**/api/orders?*', route => route.fulfill({ json: { items: [order], total: 1, page: 1, page_size: 20 } }))
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/customer-service/messages', async route => {
    requests.push(route.request().postDataJSON())
    await route.fulfill({ json: envelope({ reply: '已核对你选择的本人订单。', citations: [], cards: [] }) })
  })
  await page.goto('/?view=orders')
  const contact = page.getByRole('link', { name: '联系客服', exact: true }).first()
  await expect(contact).toHaveAttribute('href', `/customer-service.html?order=${orderNumber}`)
  await contact.click()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0].selected_order_id).toBe(orderNumber)
  await expect(page).toHaveURL(/\/customer-service\.html$/)
})

for (const state of ['missing', 'disabled'] as const) {
  test(`unavailable mode ${state} stops requests and explains availability`, async ({ page }) => {
    let consultations = 0
    let products = 0
    await page.route('**/api/customer-service/mode', route => state === 'missing'
      ? route.fulfill({ status: 404, json: { detail: 'Not Found' } })
      : route.fulfill({ json: { mode: 'integrated', enabled: false } }))
    await page.route('**/api/customer-service/pages', async route => {
      consultations += 1
      await route.fulfill({ status: 503, json: {} })
    })
    await page.route('**/api/customer-service/products?*', async route => {
      products += 1
      await route.fulfill({ status: 503, json: {} })
    })
    await page.goto('/customer-service.html')
    await page.getByRole('button', { name: '查看商城在售商品', exact: true }).click()
    await page.getByRole('button', { name: '我的订单', exact: true }).click()
    await expect(page.getByRole('log')).toContainText('客服服务尚未就绪')
    expect(consultations).toBe(0)
    expect(products).toBe(0)
  })
}
