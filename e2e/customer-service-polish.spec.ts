import { expect, test, type Page } from '@playwright/test'

const buyerId = '00000000-0000-4000-8000-000000000005'
const caseId = '00000000-0000-4000-8000-000000000003'
const orderId = '00000000-0000-4000-8000-000000000002'
const consultationId = '00000000-0000-4000-8000-000000000007'
const product = { id: '00000000-0000-4000-8000-000000000001', name: '轻盈针织开衫', category: '女装', price: '129.00', stock: 24, is_listed: true }
const detail = { order_number: orderId, product_summary: `${product.name} ×2`, status: 'pending_shipment', total: '258.00', expires_at: '2026-10-25T09:30:00+00:00', close_reason: null, shipping_company: null, tracking_number: null, shipped_at: null }
function envelope(data: Record<string, unknown>) { return { status: 'ok', request_id: crypto.randomUUID(), queried_at: new Date().toISOString(), data } }
function supportCase(overrides: Record<string, unknown> = {}) {
  return { id: caseId, kind: 'human_handoff', status: 'open', assigned: false, order_id: null,
    summary: { concern: '想了解发货进度', blocker: '当前卡点：内部路由核验', verified_facts: [{ order_id: orderId, status: 'pending_shipment', total: '258.00' }], executed_actions: [], history: [], history_shared: false },
    messages: [] as { role: string; text: string; at: string }[], created_at: new Date().toISOString(), updated_at: new Date().toISOString(), expires_at: new Date(Date.now() + 86_400_000).toISOString(), ...overrides }
}
async function ask(page: Page, text: string) {
  await page.getByRole('textbox', { name: '请输入想咨询的问题' }).fill(text)
  await page.getByRole('button', { name: '发送', exact: true }).click()
}
test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({ json: { id: buyerId, role: 'buyer' } }))
  await page.route('**/api/auth/csrf', route => route.fulfill({ json: { csrf_token: 'synthetic-csrf' } }))
  await page.route('**/api/customer-service/mode', route => route.fulfill({ json: { mode: 'integrated', enabled: true } }))
  await page.route('**/api/customer-service/faq-hints', route => route.fulfill({ json: { items: [] } }))
  await page.route('**/api/orders?*', route => route.fulfill({ json: { items: [], total: 0 } }))
  await page.route('**/api/products/*', route => route.fulfill({ json: { ...product, image_url: '/images/cardigan.svg' } }))
  await page.route('**/api/customer-service/pages', route => route.fulfill({ status: 201, json: envelope({ page_instance_id: '00000000-0000-4000-8000-000000000006', consultation_id: consultationId, handoff_token: 'a'.repeat(43) }) }))
})

test('handoff follows requested waiting assigned and closed states and routes the composer to one case', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  let current = supportCase()
  let aiMessages = 0, replies = 0
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/customer-service/messages', async route => {
    aiMessages += 1
    await gate
    await route.fulfill({ json: envelope({ reply: `已创建人工工单 ${caseId}，保存30天。`, cards: [{ type: 'support_case', case: current }], citations: [] }) })
  })
  await page.route('**/api/customer-service/cases', route => route.fulfill({ json: { items: [current] } }))
  await page.route(`**/api/customer-service/cases/${caseId}/replies`, async route => {
    replies += 1
    expect(route.request().postDataJSON()).toEqual({ text: '请帮我确认发货时间' })
    current = { ...current, messages: [{ role: 'buyer', text: '请帮我确认发货时间', at: new Date().toISOString() }] }
    await route.fulfill({ json: { case: current } })
  })
  await page.goto('/customer-service.html')
  await page.getByRole('button', { name: '转人工', exact: true }).click()
  await expect(page.locator('#service-state')).toHaveAttribute('data-state', 'HANDOFF_REQUESTED')
  await expect(page.getByLabel('请输入想咨询的问题')).toBeDisabled()
  release()
  await expect(page.locator('#service-state')).toHaveAttribute('data-state', 'WAITING_HUMAN')
  await expect(page.locator('.handoff-card')).toContainText('等待接入')
  await expect(page.getByRole('log')).not.toContainText(caseId)
  await expect(page.getByRole('log')).not.toContainText('当前卡点')
  await expect(page.getByRole('log')).not.toContainText('保存30天')
  await page.screenshot({ path: '/private/tmp/shop-cs-p3-handoff-waiting-synthetic.png', fullPage: true })
  await ask(page, '请帮我确认发货时间')
  await expect(page.locator('.case-thread')).toContainText('请帮我确认发货时间')
  expect(replies).toBe(1); expect(aiMessages).toBe(1)
  current = { ...current, assigned: true, status: 'waiting_buyer', messages: [...current.messages, { role: 'staff', text: '请补充具体问题，我们会核实。', at: new Date().toISOString() }] }
  await page.getByRole('button', { name: '刷新进度', exact: true }).click()
  await expect(page.locator('#service-state')).toHaveAttribute('data-state', 'HUMAN_ACTIVE')
  await expect(page.locator('#service-state')).toContainText('需要你补充')
  await expect(page.locator('.case-thread')).toContainText('请补充具体问题')
  await page.screenshot({ path: '/private/tmp/shop-cs-p3-handoff-active-synthetic.png', fullPage: true })
  await page.setViewportSize({ width: 320, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(320)
  const composer = await page.locator('#composer').boundingBox()
  expect(composer!.y + composer!.height).toBeLessThanOrEqual(844)
  await page.screenshot({ path: '/private/tmp/shop-cs-p3-handoff-mobile-synthetic.png', fullPage: true })
  current = { ...current, status: 'resolved' }
  await page.getByRole('button', { name: '刷新进度', exact: true }).click()
  await expect(page.locator('#service-state')).toHaveAttribute('data-state', 'CLOSED')
  await expect(page.getByLabel('请输入想咨询的问题')).toBeDisabled()
  await page.getByRole('button', { name: '返回智能客服', exact: true }).click()
  await expect(page.locator('#service-state')).toHaveAttribute('data-state', 'AI_ACTIVE')
  await expect(page.getByLabel('请输入想咨询的问题')).toBeEnabled()
  expect(replies).toBe(1)
})

test('lost supplement responses keep the draft and reconcile with GET without replay', async ({ page }) => {
  const current = supportCase()
  let posts = 0, reads = 0
  await page.route('**/api/customer-service/messages', route => route.fulfill({ json: envelope({ reply: '人工请求已受理', cards: [{ type: 'support_case', case: current }], citations: [] }) }))
  await page.route(`**/api/customer-service/cases/${caseId}/replies`, async route => { posts += 1; await route.abort('failed') })
  await page.route('**/api/customer-service/cases', async route => { reads += 1; await route.fulfill({ json: { items: [current] } }) })
  await page.goto('/customer-service.html')
  await page.getByRole('button', { name: '转人工', exact: true }).click()
  await expect(page.locator('#service-state')).toHaveAttribute('data-state', 'WAITING_HUMAN')
  await ask(page, '补充我的问题')
  await expect(page.locator('#service-state')).toContainText('发送结果待确认')
  await expect(page.getByLabel('请输入想咨询的问题')).toHaveValue('补充我的问题')
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '刷新进度', exact: true }).click()
  await expect.poll(() => reads).toBe(1)
  expect(posts).toBe(1)
  await expect(page.locator('#service-state')).toContainText('发送结果待确认')
})

for (const status of [400, 200]) {
  test(`supplement ${status === 400 ? 'rejection is retryable' : 'malformed success stays unconfirmed'}`, async ({ page }) => {
    await page.route('**/api/customer-service/messages', route => route.fulfill({ json: envelope({ reply: '已登记', cards: [{ type: 'support_case', case: supportCase() }], citations: [] }) }))
    let posts = 0
    await page.route(`**/api/customer-service/cases/${caseId}/replies`, async route => {
      posts += 1
      await route.fulfill({ status, json: status === 400 ? { detail: '补充内容不符合要求' } : { case: {} } })
    })
    await page.goto('/customer-service.html')
    await page.getByRole('button', { name: '转人工', exact: true }).click()
    await expect(page.locator('#service-state')).toHaveAttribute('data-state', 'WAITING_HUMAN')
    await ask(page, '补充内容')
    await expect(page.getByLabel('请输入想咨询的问题')).toHaveValue('补充内容')
    if (status === 400) {
      await expect(page.locator('.handoff-card')).toContainText('补充内容不符合要求')
      await expect(page.getByRole('button', { name: '发送', exact: true })).toBeEnabled()
    } else {
      await expect(page.locator('#service-state')).toContainText('发送结果待确认')
      await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled()
    }
    expect(posts).toBe(1)
  })
}

test('handoff sharing is previewed separately and failures cannot silently share again', async ({ page }) => {
  const current = supportCase()
  let shares = 0
  await page.route('**/api/customer-service/messages', route => route.fulfill({ json: envelope({ reply: '已登记', cards: [{ type: 'support_case', case: current }, { type: 'handoff_preview', summary: { ...current.summary, case_id: caseId } }], citations: [] }) }))
  await page.route('**/api/customer-service/history?*', route => route.fulfill({ json: { items: [{ role: 'user', text: '我希望人工帮我核对发货' }] } }))
  await page.route(`**/api/customer-service/cases/${caseId}/share-context`, async route => { shares += 1; expect(route.request().postDataJSON()).toEqual({ consultation_id: consultationId, consent: true }); await route.abort('failed') })
  await page.goto('/customer-service.html')
  await page.getByRole('button', { name: '转人工', exact: true }).click()
  await expect(page.locator('.handoff-card')).toHaveCount(1)
  expect(shares).toBe(0)
  await page.getByRole('button', { name: '查看交接内容', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('想了解发货进度')
  await dialog.getByRole('button', { name: '查看并选择共享聊天记录' }).click()
  await expect(dialog).toContainText('我希望人工帮我核对发货')
  expect(shares).toBe(0)
  await dialog.getByRole('button', { name: '同意共享以上必要对话' }).click()
  await expect(dialog).toContainText('发送结果待确认')
  await expect(dialog.getByRole('button', { name: '结果待核对' })).toBeDisabled()
  expect(shares).toBe(1)
})

test('settings and notifications use a separate panel with loading retry and success feedback', async ({ page }) => {
  let notificationReads = 0, writes = 0
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/customer-service/preferences', async route => {
    if (route.request().method() === 'GET') await route.fulfill({ json: { data: { categories: ['女装'], occasion: '', budget_max: '200.00' } } })
    else { writes += 1; await pending; await route.fulfill({ json: { saved: true } }) }
  })
  await page.route('**/api/customer-service/notifications', async route => {
    notificationReads += 1
    await route.fulfill(notificationReads === 1 ? { status: 503, json: {} } : { json: { items: [{ id: caseId, text: '客服已回复', read: false }] } })
  })
  await page.goto('/customer-service.html')
  const count = await page.locator('#messages > *').count()
  await page.locator('.sidebar-settings > summary').click()
  await page.getByRole('button', { name: '推荐偏好', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('预算上限（元）')).toHaveValue('200.00')
  await dialog.getByLabel('同意为后续推荐保存以上偏好90天').check()
  await dialog.getByRole('button', { name: '保存推荐偏好' }).click()
  await expect(dialog.getByRole('button', { name: '正在保存…' })).toBeDisabled()
  release()
  await expect(dialog).toContainText('推荐偏好已保存')
  expect(writes).toBe(1)
  await dialog.getByRole('button', { name: '关闭功能面板' }).click()
  await page.getByRole('button', { name: '服务通知', exact: true }).click()
  await expect(dialog).toContainText('暂时')
  await dialog.getByRole('button', { name: '重新加载' }).click()
  await expect(dialog).toContainText('客服已回复')
  expect(notificationReads).toBe(2)
  expect(await page.locator('#messages > *').count()).toBe(count)
})

test('refresh failure never invents assignment and reopening an ended case uses the reply endpoint once', async ({ page }) => {
  let current = supportCase({ status: 'resolved', assigned: true })
  let refreshes = 0, replies = 0
  await page.route('**/api/customer-service/messages', route => route.fulfill({ json: envelope({ reply: '已接入', cards: [{ type: 'support_case', case: current }], citations: [] }) }))
  await page.route('**/api/customer-service/cases', async route => {
    refreshes += 1
    await route.fulfill(refreshes === 1 ? { status: 503, json: {} } : { json: { items: [current] } })
  })
  await page.route(`**/api/customer-service/cases/${caseId}/replies`, async route => {
    replies += 1
    current = supportCase({ status: 'in_progress', assigned: true, messages: [{ role: 'buyer', text: '还有一个问题需要核对', at: new Date().toISOString() }] })
    await route.fulfill({ json: { case: current } })
  })
  await page.goto('/customer-service.html')
  await page.getByRole('button', { name: '转人工', exact: true }).click()
  await expect(page.locator('#service-state')).toHaveAttribute('data-state', 'CLOSED')
  await page.getByRole('button', { name: '刷新进度', exact: true }).click()
  await expect(page.locator('.handoff-card')).toContainText('暂时未能加载')
  await expect(page.locator('#service-state')).toHaveAttribute('data-state', 'CLOSED')
  await page.locator('.handoff-card').getByRole('button', { name: '补充问题', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('补充工单信息', { exact: true }).fill('还有一个问题需要核对')
  await dialog.getByRole('button', { name: '发送补充', exact: true }).click()
  await expect(dialog).toContainText('补充已发送')
  await expect(page.locator('#service-state')).toHaveAttribute('data-state', 'HUMAN_ACTIVE')
  expect(replies).toBe(1)
})

test('case list refresh replaces stale status inside the utility panel', async ({ page }) => {
  let current = supportCase()
  await page.route('**/api/customer-service/cases', route => route.fulfill({ json: { items: [current] } }))
  await page.goto('/customer-service.html')
  await page.getByRole('button', { name: '我的工单', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.locator('.handoff-card')).toContainText('等待接入')
  current = supportCase({ assigned: true, status: 'in_progress' })
  await dialog.getByRole('button', { name: '刷新状态', exact: true }).click()
  await expect(dialog.locator('.handoff-card')).toContainText('人工已接手')
  await expect(dialog.locator('.handoff-card')).toContainText('状态已更新')
  await expect(page.locator('#service-state')).toHaveAttribute('data-state', 'AI_ACTIVE')
})

test('new consultations invalidate old handoff buttons', async ({ page }) => {
  await page.route('**/api/customer-service/messages', route => route.fulfill({ json: envelope({ reply: '已登记', cards: [{ type: 'support_case', case: supportCase() }], citations: [] }) }))
  await page.route('**/api/customer-service/preferences', route => route.fulfill({ json: { data: {} } }))
  await page.goto('/customer-service.html')
  await page.getByRole('button', { name: '转人工', exact: true }).click()
  const oldControl = await page.locator('.handoff-card button').first().elementHandle()
  await page.getByRole('button', { name: '发起新咨询', exact: true }).click()
  await expect(page.locator('#service-state')).toHaveAttribute('data-state', 'AI_ACTIVE')
  expect(await oldControl?.evaluate((control: HTMLButtonElement) => control.disabled)).toBe(true)
  await expect(page.locator('.handoff-card')).toHaveCount(0)
  await expect(page.locator('#welcome')).toBeVisible()
})

test('products deduplicate within a response and collapse earlier results without repeating the sidebar card', async ({ page }) => {
  let turns = 0
  await page.route('**/api/customer-service/messages', async route => {
    turns += 1
    await route.fulfill({ json: envelope({ reply: '找到相关商品', cards: turns === 1 ? [{ type: 'product', product }, { type: 'product', product }, { type: 'product', product: { ...product, id: '00000000-0000-4000-8000-000000000009', name: '另一件开衫' } }] : [{ type: 'product', product: { ...product, stock: 18 } }], citations: [] }) })
  })
  await page.goto('/customer-service.html')
  await ask(page, '推荐开衫')
  await expect(page.getByRole('region', { name: '商品查询结果' })).toContainText('共找到 2 件商品')
  await expect(page.locator('.product-card')).toHaveCount(2)
  await ask(page, '再查一次开衫库存')
  await expect(page.locator('.previous-result')).toHaveCount(1)
  await expect(page.locator('.product-card:visible').filter({ hasText: product.name })).toHaveCount(1)
  await expect(page.locator('.product-card:visible').filter({ hasText: product.name })).toContainText('现货 18 件')
  await expect(page.locator('#current-context img')).toHaveCount(0)
  await expect(page.locator('#current-context')).not.toContainText('现货')
  await page.locator('.previous-result > summary').click()
  await expect(page.locator('.previous-result')).toContainText('现货 24 件')
})

test('shipping requests bind the chosen order and retry with the same frozen payload', async ({ page }) => {
  const payloads: Record<string, unknown>[] = []
  await page.route('**/api/customer-service/messages', route => route.fulfill({ json: envelope({ reply: '可登记催发货申请', cards: [{ type: 'order_detail', order: detail }, { type: 'service_request', kind: 'shipping_reminder', order_id: orderId, concern: '请尽快发货' }], citations: [] }) }))
  await page.route('**/api/customer-service/history?*', route => route.fulfill({ json: { items: [] } }))
  await page.route('**/api/customer-service/requests', async route => {
    payloads.push(route.request().postDataJSON())
    if (payloads.length === 1) await route.abort('failed')
    else await route.fulfill({ status: 201, json: { case: supportCase({ kind: 'shipping_reminder', order_id: orderId }), notice: '申请已登记' } })
  })
  await page.goto('/customer-service.html')
  await ask(page, '催发货')
  const card = page.getByRole('region', { name: '订单详情', exact: true })
  await expect(card).toContainText('订单尾号 0002')
  await expect(card.getByText(`订单号：${orderId}`)).not.toBeVisible()
  await card.getByText('完整订单信息', { exact: true }).click()
  await expect(card).toContainText(orderId)
  await page.getByRole('button', { name: '申请催发货', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('我已核对申请内容，同意交给客服并保存30天').check()
  await dialog.getByRole('button', { name: '确认提交申请' }).click()
  await expect(dialog).toContainText('发送结果待确认')
  await expect(dialog.getByLabel('问题和期望处理方式')).toBeDisabled()
  await dialog.getByRole('button', { name: '关闭功能面板' }).click()
  await page.getByRole('button', { name: '申请催发货', exact: true }).click()
  await expect(dialog.getByLabel('问题和期望处理方式')).toBeDisabled()
  await expect(dialog).toContainText('发送结果待确认')
  await dialog.getByRole('button', { name: '重试同一申请' }).click()
  await expect(dialog).toContainText('申请已登记')
  expect(payloads).toHaveLength(2)
  expect(payloads[1]).toEqual(payloads[0])
  expect(payloads[0].selected_order_id).toBe(orderId)
  expect(payloads[0].client_request_id).toBeTruthy()
  await expect(page.locator('#service-state')).toHaveAttribute('data-state', 'AI_ACTIVE')
})
