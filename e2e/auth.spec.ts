import { expect, test } from '@playwright/test'

const demoPassword = 'demo-only-password-123'

test('buyer can register, log in, refresh, is denied admin access, and log out', async ({ page }) => {
  const email = `phase2-${Date.now()}@example.com`
  await page.goto('/')
  await expect(page.getByText('春日轻盈针织开衫')).toBeVisible()
  await page.getByRole('button', { name: '免费注册' }).click()
  const register = page.getByRole('dialog')
  await expect(register.getByText('不要使用真实账号的密码')).toBeVisible()
  await register.locator('input[name=email]').fill(email)
  await register.locator('input[name=password]').fill(demoPassword)
  await register.locator('form button[type=submit]').click()
  await expect(page.getByText('注册成功，请登录。')).toBeVisible()

  const login = page.getByRole('dialog')
  await login.locator('input[name=email]').fill(email)
  await login.locator('input[name=password]').fill(demoPassword)
  await login.locator('form button[type=submit]').click()
  await expect(page.getByText(email).first()).toBeVisible()
  await page.reload()
  await expect(page.getByText(email).first()).toBeVisible()

  await page.getByRole('button', { name: '管理后台' }).first().click()
  await expect(page.getByText('无权限：当前账号不是管理员。')).toBeVisible()
  await page.getByRole('button', { name: '关闭' }).click()
  await page.getByRole('button', { name: '退出登录' }).click()
  await expect(page.getByText('已安全退出。')).toBeVisible()
})

test('administrator can access the protected admin page', async ({ page }) => {
  test.skip(!process.env.SHOP_TEST_ADMIN_PASSWORD, 'Requires an explicitly configured demo admin password')
  await page.goto('/')
  await page.getByRole('button', { name: '管理后台' }).click()
  await expect(page.getByText('请先登录管理员账号。')).toBeVisible()
  await page.getByRole('button', { name: '关闭' }).click()
  await page.getByRole('button', { name: '亲，请登录' }).click()
  const login = page.getByRole('dialog')
  await login.locator('input[name=email]').fill('admin@example.com')
  await login.locator('input[name=password]').fill(process.env.SHOP_TEST_ADMIN_PASSWORD ?? '')
  await login.locator('form button[type=submit]').click()
  await expect(page.getByText('admin@example.com').first()).toBeVisible()
  await page.getByRole('button', { name: '管理后台' }).first().click()
  await expect(page.getByText('管理员访问已授权')).toBeVisible()
})
