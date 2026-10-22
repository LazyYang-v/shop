import { expect, test } from '@playwright/test'

const buyer = { id: 'page-demo-buyer', email: 'pages@example.com', role: 'buyer' }

test('home channel entries open real products and preserve category on reload', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('navigation', { name: '主要导航' }).getByRole('link', { name: '数码生活' }).click()
  await expect(page.getByRole('heading', { name: '让生活多一点灵感' })).toBeVisible()
  await expect(page.locator('.channel-products article').first()).toBeVisible()
  await page.getByRole('navigation', { name: '频道商品分类' }).getByRole('link', { name: '办公' }).click()
  await page.reload()
  await expect(page.getByRole('navigation', { name: '频道商品分类' }).getByRole('link', { name: '办公' })).toHaveAttribute('aria-current', 'page')
  await page.locator('.channel-products article a').first().click()
  await expect(page.locator('.product-detail-page')).toBeVisible()
})

test('order shortcut consumes status and browser history restores the filter', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({ json: buyer }))
  const statuses: string[] = []
  await page.route('**/api/orders?*', route => {
    statuses.push(new URL(route.request().url()).searchParams.get('status') ?? '')
    return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20 } })
  })
  await page.goto('/')
  await page.locator('.quick-links a[href="?view=orders&status=pending_shipment"]').click()
  await expect(page.getByRole('button', { name: '待发货', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(() => statuses.includes('pending_shipment')).toBe(true)
  await page.getByRole('button', { name: '待收货', exact: true }).click()
  await expect(page).toHaveURL(/status=pending_receipt/)
  await page.goBack()
  await expect(page.getByRole('button', { name: '待发货', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.reload()
  await expect(page.getByRole('button', { name: '待发货', exact: true })).toHaveAttribute('aria-pressed', 'true')
})

test('new pages fit mobile screens and provide usable navigation', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const url of ['/', '/?view=channel&channel=home', '/?view=help', '/?view=notices', '/?view=directory', '/?view=mobile', '/?view=account', '/?view=addresses', '/?view=admin']) {
    await page.goto(url)
    await expect(page.locator('main')).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
})

test('administrator can submit shipment details and see the updated state', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({ json: { ...buyer, role: 'admin' } }))
  await page.route('**/api/auth/csrf', route => route.fulfill({ json: { csrf_token: 'demo-csrf' } }))
  let order = { id: 'order-one', status: 'pending_shipment', total: '20.00', created_at: '2026-10-22T00:00:00Z', expires_at: '2026-10-22T00:30:00Z', paid_at: '2026-10-22T00:01:00Z', shipped_at: null as string | null, completed_at: null, closed_at: null, close_reason: null, shipping_company: null as string | null, tracking_number: null as string | null, items: [{ product_id: 'product-one', name: '演示商品', image_url: '', unit_price: '20.00', quantity: 1, line_total: '20.00' }], address: { recipient_name: '演示买家', phone: '13800000000', province: '浙江省', city: '杭州市', district: '西湖区', detail: '演示路 1 号' } }
  await page.route('**/api/admin/orders?*', route => route.fulfill({ json: { items: [order], total: 1, page: 1, page_size: 20 } }))
  await page.route('**/api/admin/orders/order-one', route => route.fulfill({ json: order }))
  await page.route('**/api/admin/orders/order-one/ship', async route => {
    expect(route.request().postDataJSON()).toEqual({ shipping_company: '演示快递', tracking_number: 'DEMO123456' })
    order = { ...order, ...route.request().postDataJSON(), status: 'pending_receipt', shipped_at: '2026-10-22T01:00:00Z' }
    await route.fulfill({ json: order })
  })
  await page.goto('/?view=admin&tab=orders')
  await page.getByRole('button', { name: '查看详情 / 发货' }).click()
  await page.getByLabel('物流公司', { exact: true }).fill('演示快递')
  await page.getByLabel('运单号码', { exact: true }).fill('DEMO123456')
  await page.getByRole('button', { name: '确认发货', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('发货成功')
  await expect(page.locator('.admin-order-summary')).toContainText('待收货')
  await expect(page.getByRole('button', { name: '确认发货', exact: true })).toHaveCount(0)
})

test('help search and notices provide readable detail pages', async ({ page }) => {
  await page.goto('/?view=help')
  await expect(page.locator('details').first()).toBeVisible()
  await page.locator('details summary').first().click()
  await expect(page.locator('details').first()).toHaveAttribute('open', '')
  await page.goto('/?view=notices')
  await page.locator('a[href*="notice=simulated-payment"]').first().click()
  await expect(page).toHaveURL(/notice=simulated-payment/)
  await expect(page.locator('main')).toContainText('模拟支付')
})

test('administrator can edit products and record inventory adjustments', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({ json: { ...buyer, role: 'admin' } }))
  await page.route('**/api/auth/csrf', route => route.fulfill({ json: { csrf_token: 'demo-csrf' } }))
  let product = { id: 'product-one', name: '演示商品', category: '办公', description: '演示商品描述', image_url: '/images/products/pexels-5794263.jpg', price: '20.00', stock: 10, is_listed: true, created_at: '2026-10-22T00:00:00Z' }
  await page.route('**/api/admin/products?*', route => route.fulfill({ json: { items: [product], total: 1, page: 1, page_size: 20 } }))
  await page.route('**/api/admin/products/product-one', async route => {
    if (route.request().method() === 'PATCH') product = { ...product, ...route.request().postDataJSON() }
    await route.fulfill({ json: product })
  })
  await page.route('**/api/admin/products/product-one/inventory-adjustments?*', route => route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20 } }))
  await page.route('**/api/admin/products/product-one/inventory-adjustments', async route => {
    const input = route.request().postDataJSON()
    expect(input).toEqual({ delta: 5, reason: '演示补货' })
    expect(route.request().headers()['x-csrf-token']).toBe('demo-csrf')
    product = { ...product, stock: product.stock + input.delta }
    await route.fulfill({ json: { ...input, id: 'adjustment-one' } })
  })
  await page.goto('/?view=admin')
  await page.getByRole('button', { name: '编辑 / 库存' }).click()
  await page.getByLabel('商品名称').fill('已编辑演示商品')
  await page.getByRole('button', { name: '保存商品', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('商品信息已保存')
  await page.getByLabel('调整数量').fill('5')
  await page.getByLabel('调整原因').fill('演示补货')
  await page.getByRole('button', { name: '确认调整', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('库存已调整')
  await expect(page.locator('.admin-muted').filter({ hasText: '当前可售库存' })).toContainText('15')
})

test('address page reads persisted addresses and saves edits through the API', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({ json: buyer }))
  let address = { id: 'address-one', recipient_name: '演示买家', phone: '13800000000', province: '浙江省', city: '杭州市', district: '西湖区', detail: '演示路 1 号', is_default: true }
  await page.route('**/api/addresses', route => route.fulfill({ json: { items: [address] } }))
  await page.route('**/api/addresses/address-one', async route => {
    expect(route.request().method()).toBe('PATCH')
    address = { ...address, ...route.request().postDataJSON() }
    await route.fulfill({ json: address })
  })
  await page.route('**/api/auth/csrf', route => route.fulfill({ json: { csrf_token: 'demo-csrf' } }))
  await page.goto('/?view=addresses')
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  await page.getByLabel('详细地址').fill('演示路 2 号')
  await page.getByRole('button', { name: '保存地址', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('收货地址已更新')
  await page.reload()
  await expect(page.locator('.account-address-location')).toContainText('演示路 2 号')
})
