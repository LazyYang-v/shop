import { expect, test } from '@playwright/test'

test('catalog search, category, sort and query state are server-backed and URL-persistent', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.product-card').first()).toBeVisible()
  await page.getByRole('textbox', { name: '搜索你想要的商品' }).fill('针织')
  await page.getByRole('button', { name: '搜索' }).click()
  await expect(page).toHaveURL(/q=%E9%92%88%E7%BB%87/)
  await expect(page.locator('.product-card').filter({ hasText: '柔雾日常针织上衣' })).toBeVisible()
  await page.getByLabel('商品分类').selectOption('女装')
  await page.getByLabel('排序方式').selectOption('price_desc')
  await expect(page).toHaveURL(/category=%E5%A5%B3%E8%A3%85/)
  await expect(page).toHaveURL(/sort=price_desc/)
  await page.reload()
  await expect(page.getByLabel('排序方式')).toHaveValue('price_desc')
  await expect(page.getByLabel('商品分类')).toHaveValue('女装')
})

test('search results show active query, load images and clear the search input', async ({ page }) => {
  await page.goto('/?q=' + encodeURIComponent('笔记本'))
  await expect(page.locator('.catalog-summary')).toContainText('笔记本')
  await expect(page.locator('.product-card')).toHaveCount(5)
  const images = page.locator('.product-card .product-image')
  await expect.poll(() => images.evaluateAll(elements => elements.every(element => {
    const image = element as HTMLImageElement
    return image.complete && image.naturalWidth > 0
  }))).toBe(true)
  await page.getByRole('button', { name: '清除筛选', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '搜索你想要的商品' })).toHaveValue('')
  await expect(page).not.toHaveURL(/q=/)
  await expect(page.locator('.product-card')).toHaveCount(20)
})

test('mobile search fits the viewport and supports category filtering', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/?q=' + encodeURIComponent('笔记本'))
  await expect(page.locator('.product-card')).toHaveCount(5)
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByLabel('商品分类', { exact: true }).selectOption('办公')
  await expect(page).toHaveURL(/category=/)
  await expect(page.locator('.filter-chip').filter({ hasText: '办公' })).toBeVisible()
})

test('product detail uses a constrained image and two-column desktop layout', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/')
  await page.locator('.product-card').first().click()
  const detail = page.locator('.product-detail-page')
  const image = detail.locator('.product-detail-image')
  const info = detail.locator('.product-detail-info')
  await expect(detail).toBeVisible()
  await expect(image).toBeVisible()
  await expect(info).toBeVisible()
  await expect(detail.getByText('米白色', { exact: true })).toHaveCount(0)
  const layout = await detail.evaluate(element => getComputedStyle(element).gridTemplateColumns)
  const imageWidth = await image.evaluate(element => element.getBoundingClientRect().width)
  const imageHeight = await image.evaluate(element => element.getBoundingClientRect().height)
  const buttonStyle = await detail.getByRole('button', { name: '加入购物车' }).evaluate(element => getComputedStyle(element).backgroundImage)
  await page.screenshot({ path: '/tmp/shop-product-detail.png', fullPage: true })
  expect(layout.split(' ')).toHaveLength(2)
  expect(imageWidth).toBeLessThanOrEqual(520)
  expect(imageHeight).toBeLessThanOrEqual(520)
  expect(buttonStyle).toContain('linear-gradient')
})

test('administrator sees why cart adding is unavailable without sending a cart request', async ({ page }) => {
  let addRequests = 0
  await page.route('**/api/auth/me', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'admin-id', email: 'admin@example.com', role: 'admin' }) }))
  await page.route('**/api/cart/items', route => { addRequests += 1; return route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ detail: '无权执行此操作' }) }) })
  await page.goto('/')
  await expect(page.getByText('admin@example.com').first()).toBeVisible()
  await page.locator('.product-card').first().click()
  await page.getByRole('button', { name: '加入购物车' }).click()
  await expect(page.getByRole('status')).toContainText('管理员账号不能使用买家购物车，请切换买家账号。')
  expect(addRequests).toBe(0)
})
