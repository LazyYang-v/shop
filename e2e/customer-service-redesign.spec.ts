import { expect, test } from '@playwright/test'

const buyerId = '00000000-0000-4000-8000-000000000005'
const product = { id: '00000000-0000-4000-8000-000000000001', name: '日常轻盈针织开衫', category: '女装', price: '129.00', stock: 24, is_listed: true }
const orderId = '00000000-0000-4000-8000-000000000002'
const consultationIds = ['00000000-0000-4000-8000-000000000007', '00000000-0000-4000-8000-000000000008']
const detail = { order_number: orderId, product_summary: `${product.name} ×1`, status: 'pending_receipt', total: '129.00',
  expires_at: '2026-10-25T09:30:00+00:00', close_reason: null, shipping_company: '合成速运', tracking_number: 'DEMO-TRACK-01', shipped_at: '2026-10-25T10:00:00+00:00' }
const order = { id: orderId, status: 'pending_receipt', total: '129.00', created_at: '2026-10-25T09:00:00+00:00',
  items: [{ product_id: product.id, name: product.name, image_url: '/images/cardigan.svg', quantity: 1, unit_price: '129.00', line_total: '129.00' }] }
function envelope(data: Record<string, unknown>) {
  return { status: 'ok', request_id: '00000000-0000-4000-8000-000000000004', queried_at: '2026-10-25T12:00:00+00:00', data }
}
test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({ json: { id: buyerId, role: 'buyer', email: 'synthetic-buyer@example.com' } }))
  await page.route('**/api/auth/csrf', route => route.fulfill({ json: { csrf_token: 'synthetic-csrf' } }))
  await page.route('**/api/customer-service/mode', route => route.fulfill({ json: { mode: 'integrated', enabled: true } }))
  await page.route('**/api/customer-service/faq-hints', route => route.fulfill({ json: { items: [] } }))
  await page.route('**/api/orders?*', route => route.fulfill({ json: { items: [order], total: 1, page: 1, page_size: 50 } }))
  await page.route(`**/api/products/${product.id}`, route => route.fulfill({ json: { ...product, image_url: '/images/cardigan.svg' } }))
  await page.route('**/api/customer-service/pages', route => route.fulfill({ status: 201, json: envelope({
    page_instance_id: '00000000-0000-4000-8000-000000000006', consultation_id: consultationIds[0], handoff_token: 'a'.repeat(43),
  }) }))
})

test('desktop workspace keeps three columns, compact cards and the storefront return state', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/?category=女装&q=针织&page=2')
  await page.getByRole('link', { name: /联系客服/ }).first().click()
  await expect(page.locator('#welcome')).toBeVisible()
  await expect(page.getByRole('complementary', { name: '服务导航' })).toBeVisible()
  await expect(page.getByRole('complementary', { name: '订单与商品' })).toBeVisible()
  await expect(page.locator('.header-back')).toHaveAttribute('href', '/?category=%E5%A5%B3%E8%A3%85&q=%E9%92%88%E7%BB%87&page=2')
  await expect(page.locator('#sidebar-orders img')).toBeVisible()
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/customer-service/messages', async route => {
    requests.push(route.request().postDataJSON())
    await route.fulfill({ json: envelope({ reply: '已核对你选择的本人订单。', cards: [{ type: 'order_detail', order: detail }], citations: [], parts: [{ source: 'get_my_order', status: 'ok', queried_at: '2026-10-25T12:00:00+00:00' }] }) })
  })
  await page.getByRole('button', { name: '发送给智能客服', exact: true }).click()
  await expect(page.getByRole('region', { name: '订单详情', exact: true })).toContainText('合成速运')
  await expect(page.locator('.logistics-timeline')).toContainText('商家已发货')
  await expect(page.locator('#current-context')).toContainText(product.name)
  const evidence = page.locator('.reply-evidence')
  await expect(evidence).not.toHaveAttribute('open')
  await evidence.getByText('答复依据', { exact: true }).click()
  await expect(evidence).toContainText('订单详情：已核验')
  await expect(page.locator('#welcome')).toBeHidden()
  expect(requests[0].selected_order_id).toBe(orderId)
  await page.locator('#current-context').getByRole('button', { name: '查询服务进度', exact: true }).click()
  await expect.poll(() => requests.length).toBe(2)
  expect(requests[1]).toMatchObject({ selected_order_id: orderId, text: '查询售后进度' })
  expect(await page.locator('.bubble').first().evaluate(element => parseFloat(getComputedStyle(element).fontSize))).toBeLessThanOrEqual(15)
})

test('multiline composer handles line breaks, composition, loading and one send', async ({ page }) => {
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/customer-service/messages', async route => {
    requests.push(route.request().postDataJSON())
    await pending
    await route.fulfill({ json: envelope({ reply: '已收到你的两行问题。正在按商城信息核对。', cards: [], citations: [] }) })
  })
  await page.goto('/customer-service.html')
  const input = page.getByRole('textbox', { name: '请输入想咨询的问题' })
  await input.fill('第一行')
  await input.press('Shift+Enter')
  await input.pressSequentially('第二行')
  await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true })
  expect(requests).toHaveLength(0)
  await input.press('Enter')
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0].text).toBe('第一行\n第二行')
  await expect(page.locator('#reply-status')).toBeVisible()
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled()
  await input.fill('下一条问题')
  await input.press('Enter')
  expect(requests).toHaveLength(1)
  await expect(input).toHaveValue('下一条问题')
  release()
  await expect(page.getByRole('log')).toContainText('已收到你的两行问题')
  await expect(page.locator('#reply-status')).toBeHidden()
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeEnabled()
})

test('history switches between server records and refresh restores a real recent record', async ({ page }) => {
  let pages = 0
  let messages = 0
  const pageBodies: Record<string, unknown>[] = []
  await page.route('**/api/customer-service/pages', async route => {
    pageBodies.push(route.request().postDataJSON())
    await route.fulfill({ status: 201, json: envelope({ page_instance_id: `page-${++pages}`, consultation_id: consultationIds[Math.min(pages - 1, 1)], handoff_token: 'a'.repeat(43) }) })
  })
  await page.route('**/api/customer-service/messages', async route => {
    messages += 1
    await route.fulfill({ json: envelope({ reply: '已核对咨询。', cards: [], citations: [] }) })
  })
  const historyReads: string[] = []
  await page.route('**/api/customer-service/history?*', async route => {
    const id = new URL(route.request().url()).searchParams.get('consultation_id') || ''
    historyReads.push(id)
    await route.fulfill({ json: { retention: '当前咨询空闲30分钟后过期', items: [
      { role: 'user', text: id === consultationIds[0] ? '第一段真实服务端历史' : '第二段真实服务端历史' },
      { role: 'assistant', text: '这是接口返回的对话记录。' },
    ] } })
  })
  await page.goto('/customer-service.html')
  const input = page.getByRole('textbox', { name: '请输入想咨询的问题' })
  await input.fill('商品咨询')
  await input.press('Enter')
  await expect(page.locator('.history-entry')).toHaveCount(1)
  await page.getByRole('button', { name: '发起新咨询', exact: true }).click()
  await expect(page.locator('#welcome')).toBeVisible()
  await input.fill('查询物流')
  await input.press('Enter')
  await expect(page.locator('.history-entry')).toHaveCount(2)
  expect(pageBodies).toEqual([{}, {}])
  await page.locator('.history-entry').nth(1).click()
  await expect(page.locator('#history-view')).toContainText('第一段真实服务端历史')
  await expect(page.locator('#composer')).toBeHidden()
  await page.locator('.history-entry').first().click()
  await expect(page.locator('#history-view')).toContainText('第二段真实服务端历史')
  expect(messages).toBe(2)
  await page.reload()
  await expect(page.locator('.history-entry')).toHaveCount(2)
  await page.locator('.history-entry').first().click()
  await expect(page.locator('#history-view')).toContainText('第二段真实服务端历史')
  await page.getByRole('button', { name: '返回当前咨询', exact: true }).click()
  await expect(page.locator('#composer')).toBeVisible()
  expect(historyReads).toHaveLength(3)
  expect(messages).toBe(2)
  const saved = await page.evaluate(() => sessionStorage.getItem('shop.customer-service.recent'))
  expect(saved).not.toContain('真实服务端历史')
  expect(saved).not.toContain('确认凭据')
})

test('expired history is removed and a failed handoff never claims success', async ({ page }) => {
  await page.route('**/api/customer-service/messages', route => route.fulfill({ json: envelope({ reply: '已收到问题', cards: [], citations: [] }) }))
  await page.route('**/api/customer-service/history?*', route => route.fulfill({ status: 403, json: { detail: '未找到可访问的记录' } }))
  await page.goto('/customer-service.html')
  await page.getByRole('textbox', { name: '请输入想咨询的问题' }).fill('请帮我')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.locator('.history-entry')).toHaveCount(1)
  await page.locator('.history-entry').click()
  await expect(page.locator('#history-view')).toContainText('已过期')
  await expect(page.locator('.history-entry')).toHaveCount(0)
  await page.route('**/api/customer-service/messages', route => route.fulfill({ status: 503, json: { code: 'mcp_unavailable' } }))
  await page.getByRole('button', { name: '转人工', exact: true }).click()
  await expect(page.getByRole('log')).toContainText('暂不可用')
  await expect(page.getByRole('log')).not.toContainText('转接成功')
  await expect(page.getByRole('log')).not.toContainText('已创建人工交接工单')
})

test('product cards use actual image details and show price inventory and specifications', async ({ page }) => {
  await page.route('**/api/customer-service/messages', route => route.fulfill({ json: envelope({ reply: '找到这件商品。', cards: [{ type: 'product', product }], citations: [] }) }))
  await page.goto('/customer-service.html')
  await page.getByRole('textbox', { name: '请输入想咨询的问题' }).fill('针织开衫')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const card = page.getByRole('region', { name: '商城商品', exact: true })
  await expect(card.locator('img')).toHaveAttribute('src', '/images/cardigan.svg')
  await expect(card).toContainText('¥129.00')
  await expect(card).toContainText('现货 24 件')
  await expect(card).toContainText('单规格 · 正常销售')
  await expect(card.getByRole('link', { name: '商品详情' })).toHaveAttribute('href', `/?product=${product.id}`)
})

test('external product images keep the local placeholder and issue no external request', async ({ page }) => {
  const external: string[] = []
  page.on('request', request => { if (request.url().includes('untrusted.example')) external.push(request.url()) })
  await page.route(`**/api/products/${product.id}`, route => route.fulfill({ json: { ...product, image_url: 'https://untrusted.example/tracker.png' } }))
  await page.route('**/api/customer-service/messages', route => route.fulfill({ json: envelope({ reply: '已找到商品', cards: [{ type: 'product', product }], citations: [] }) }))
  await page.goto('/customer-service.html')
  const productResponse = page.waitForResponse(response => response.url().endsWith(`/api/products/${product.id}`))
  await page.getByRole('textbox', { name: '请输入想咨询的问题' }).fill('查看商品')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await productResponse
  const card = page.getByRole('region', { name: '商城商品', exact: true })
  await expect(card.locator('.product-thumbnail svg')).toBeVisible()
  await expect(card.locator('img')).toHaveCount(0)
  expect(external).toEqual([])
})

for (const width of [320, 390, 768, 1024]) {
  test(`workspace keeps the composer and drawers usable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 })
    await page.goto('/customer-service.html')
    await expect(page.getByRole('textbox', { name: '请输入想咨询的问题' })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    const composer = await page.locator('#composer').boundingBox()
    expect(composer!.y + composer!.height).toBeLessThanOrEqual(844)
    await page.getByRole('button', { name: '打开订单与商品', exact: true }).click()
    await expect(page.getByRole('complementary', { name: '订单与商品' })).toBeVisible()
    await expect(page.getByRole('button', { name: '发送给智能客服', exact: true })).toBeVisible()
    await page.getByRole('button', { name: '关闭订单与商品', exact: true }).click()
    if (width <= 800) {
      await page.getByRole('button', { name: '打开服务导航', exact: true }).click()
      await expect(page.getByRole('button', { name: '发起新咨询', exact: true })).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(page.getByRole('complementary', { name: '服务导航' })).toBeHidden()
    }
  })
}
