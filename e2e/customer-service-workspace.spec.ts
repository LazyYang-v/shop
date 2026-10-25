import { expect, test } from '@playwright/test'

const admin = { id: '11111111-1111-4111-8111-111111111111', email: 'support-admin@example.com', role: 'admin' }
const caseId = '22222222-2222-4222-8222-222222222222'
const productId = '33333333-3333-4333-8333-333333333333'
const initialVersion = '2026-10-25T01:00:00.123456+00:00'
const definitions = {
  resolution_rate: '在窗口内提交反馈的咨询中，买家明确标记已解决的比例',
  handoff_rate: '在窗口内有对话的咨询中，触发人工升级的比例（不等于人工接手）',
  tool_success_rate: '工具调用正常返回次数 / 工具调用总次数（空结果也计正常）',
  retrieval_hit_rate: '找到当前有效且无冲突依据的检索次数 / 检索总次数',
  satisfaction: '4或5分反馈数 / 有评分反馈数',
}

test.use({ timezoneId: 'Asia/Shanghai', viewport: { width: 1280, height: 900 } })
test.beforeEach(async ({ page }) => {
  // Fulfill every API call so this spec never reaches the database.
  // Match by path prefix: '**/api/**' also catches /src/api/*.ts module requests.
  await page.route(url => url.pathname.startsWith('/api/'), route => {
    const path = new URL(route.request().url()).pathname
    const json = path === '/api/auth/me' || path === '/api/admin/access' ? admin
      : path === '/api/auth/csrf' ? { csrf_token: 'workspace-csrf' }
        : { items: [], total: 0, page: 1, page_size: 20 }
    return route.fulfill({ json })
  })
})

test('case reviews preserve the version, require address consent, and recover from a stale conflict', async ({ page }, testInfo) => {
  let item = {
    id: caseId, kind: 'address_change', kind_label: '修改收货地址', status: 'open', priority: 'urgent',
    order_id: '44444444-4444-4444-8444-444444444444', buyer_id: 'buyer-one', assigned: false,
    assigned_to: null as string | null, created_at: initialVersion, updated_at: initialVersion, expires_at: '2026-11-24T01:00:00Z',
    details: { address_id: '55555555-5555-4555-8555-555555555555' },
    summary: {
      concern: '请修改为买家选择的地址', blocker: '等待核对待发货订单', escalation_reason: 'buyer_request',
      verified_facts: [{ source: 'get_my_order', status: 'pending_shipment' }],
      executed_actions: [] as Array<{ action: string }>, history_shared: true,
      history: [{ role: 'user', text: '请人工核对地址修改申请' }],
    },
    messages: [] as Array<{ role: string; text: string; at: string }>,
  }
  const reviews: Array<Record<string, unknown>> = []
  await page.route('**/api/admin/customer-service/cases?*', route => route.fulfill({ json: { items: [item], total: 1, page: 1 } }))
  await page.route(`**/api/admin/customer-service/cases/${caseId}`, async route => {
    expect(route.request().method()).toBe('PATCH')
    expect(route.request().headers()['x-csrf-token']).toBe('workspace-csrf')
    const input = route.request().postDataJSON()
    reviews.push(input)
    if (reviews.length === 2) {
      item = { ...item, status: 'waiting_buyer', updated_at: '2026-10-25T01:02:00.345678+00:00' }
      await route.fulfill({ status: 409, json: { detail: '工单已被更新，请刷新后重试' } })
      return
    }
    item = {
      ...item, status: input.status, assigned: true, assigned_to: admin.id,
      updated_at: reviews.length === 1 ? '2026-10-25T01:01:00.234567+00:00' : '2026-10-25T01:03:00.456789+00:00',
      messages: [...item.messages, { role: 'staff', text: input.reply, at: '2026-10-25T01:01:00Z' }],
      summary: { ...item.summary, executed_actions: input.apply_address ? [{ action: 'address_change' }] : [] },
    }
    await route.fulfill({ json: { case: item } })
  })
  await page.goto('/?view=admin&tab=support')
  await expect(page.getByRole('link', { name: '客服工作台', exact: true })).toHaveAttribute('aria-current', 'page')
  await page.getByRole('button', { name: `查看修改收货地址工单 ${caseId}` }).click()
  const detail = page.getByRole('region', { name: '所选工单详情' })
  await expect(detail).toContainText('等待核对待发货订单')
  await expect(detail).toContainText('get_my_order')
  await detail.locator('summary').click()
  await expect(detail).toContainText('请人工核对地址修改申请')
  await page.screenshot({ path: testInfo.outputPath('support-admin-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('support-admin-mobile.png'), fullPage: true })
  await page.setViewportSize({ width: 1280, height: 900 })

  await detail.getByLabel('给买家的回复').fill('已接手，正在核对订单状态')
  await detail.getByRole('button', { name: '提交审核与回复' }).click()
  await expect(page.getByRole('status')).toContainText('回复与工单状态已保存')
  expect(reviews[0]).toEqual({ status: 'in_progress', reply: '已接手，正在核对订单状态', expected_updated_at: initialVersion, apply_address: false })

  await detail.getByLabel('处理状态').selectOption('resolved')
  const consent = detail.getByRole('checkbox', { name: /明确应用买家选择的地址簿地址/ })
  await expect(consent).not.toBeChecked()
  await consent.check()
  await detail.getByLabel('给买家的回复').fill('已核对，请应用所选地址')
  await detail.getByRole('button', { name: '提交审核与回复' }).click()
  await expect(page.getByRole('alert')).toContainText('工单已被更新，请刷新后重试')
  expect(reviews[1]).toEqual({ status: 'resolved', reply: '已核对，请应用所选地址', expected_updated_at: '2026-10-25T01:01:00.234567+00:00', apply_address: true })
  await expect(detail.getByLabel('给买家的回复')).toBeDisabled()
  await detail.getByRole('button', { name: '载入新版本' }).click()
  await expect(detail.getByLabel('给买家的回复')).toBeEmpty()
  await detail.getByLabel('处理状态').selectOption('resolved')
  await expect(consent).not.toBeChecked()
  await consent.check()
  await detail.getByLabel('给买家的回复').fill('重新核对后应用买家所选地址')
  await detail.getByRole('button', { name: '提交审核与回复' }).click()
  await expect(page.getByRole('status')).toContainText('已应用买家选择的地址')
  expect(reviews[2]?.expected_updated_at).toBe('2026-10-25T01:02:00.345678+00:00')
  await expect(detail).toContainText('address_change')
  await expect(detail.getByRole('button', { name: '提交审核与回复' })).toHaveCount(0)
})

test('knowledge publishes exact schema fields and reuses a version as a draft', async ({ page }) => {
  const entries: Array<Record<string, unknown>> = []
  const publications: Array<Record<string, unknown>> = []
  await page.route('**/api/admin/customer-service/knowledge', async route => {
    if (route.request().method() === 'POST') {
      expect(route.request().headers()['x-csrf-token']).toBe('workspace-csrf')
      const input = route.request().postDataJSON()
      publications.push(input)
      entries.push({ ...input, id: 'knowledge-one', version: 4 })
      await route.fulfill({ status: 201, json: { id: 'knowledge-one', version: 4, state: input.state } })
    } else await route.fulfill({ json: { items: entries } })
  })
  await page.route('**/api/admin/customer-service/knowledge/knowledge-one/retire', async route => {
    expect(route.request().method()).toBe('POST')
    entries[0] = { ...entries[0], state: 'retired' }
    await route.fulfill({ json: { state: 'retired' } })
  })
  await page.goto('/?view=admin&tab=support')
  await page.getByRole('button', { name: '知识库', exact: true }).click()
  await page.getByLabel('知识类型').selectOption('product')
  await page.getByLabel('主题（用于版本分组）').fill('linen_shirt')
  await page.getByLabel('标题', { exact: true }).fill('棉衬衫规格说明')
  await page.getByLabel('商品编号（UUID，商品知识必填）').fill(productId)
  await page.getByLabel('来源', { exact: true }).fill('商品规格表 2026-10')
  await page.getByLabel('保存状态').selectOption('published')
  await page.getByLabel('生效开始').fill('2026-10-25T09:00')
  await page.getByLabel('生效结束（留空为长期）').fill('2026-11-25T09:00')
  await page.getByLabel('正文', { exact: true }).fill('以商品规格表为准，M 码胸围 96 厘米。')
  await page.getByLabel('关键词（每行一项，最多 20 项，每项 80 字符）').fill('衬衫\n尺码')
  const attributes = { material: '棉', specs: { 颜色: '白' }, size_chart: { M: { height_cm: [160, 170], weight_kg: [50, 60] } }, tags: ['日常'] }
  await page.getByLabel('结构化属性（JSON 对象）').fill('[]')
  await page.getByRole('button', { name: '创建知识版本', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('必须是 JSON 对象')
  expect(publications).toHaveLength(0)
  await page.getByLabel('结构化属性（JSON 对象）').fill(JSON.stringify({ size_chart: [{ 尺码: 'M', 胸围_cm: 96 }] }))
  await page.getByRole('button', { name: '创建知识版本', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('尺码表须为')
  expect(publications).toHaveLength(0)
  await page.getByLabel('结构化属性（JSON 对象）').fill(JSON.stringify(attributes))
  await page.getByRole('button', { name: '创建知识版本', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: '已创建 v4' })).toBeVisible()
  expect(publications).toEqual([{
    kind: 'product', topic: 'linen_shirt', title: '棉衬衫规格说明', body: '以商品规格表为准，M 码胸围 96 厘米。',
    source: '商品规格表 2026-10', keywords: ['衬衫', '尺码'], attributes, product_id: productId,
    state: 'published', valid_from: '2026-10-25T01:00:00.000Z', valid_until: '2026-11-25T01:00:00.000Z',
  }])
  await page.getByRole('button', { name: '复用知识 棉衬衫规格说明 v4', exact: true }).click()
  await expect(page.getByLabel('保存状态')).toHaveValue('draft')
  await expect(page.getByLabel('来源', { exact: true })).toHaveValue('商品规格表 2026-10')
  expect(JSON.parse(await page.getByLabel('结构化属性（JSON 对象）').inputValue())).toEqual(attributes)
  await page.getByRole('button', { name: '停用知识 棉衬衫规格说明 v4', exact: true }).click()
  await expect(page.locator('tbody tr')).toContainText('已停用')
})

test('five channels retain truthful connection status after local configuration', async ({ page }) => {
  const channels = ['storefront', 'taobao', 'jd', 'douyin', 'pinduoduo'].map(name => ({
    name, connected: name === 'storefront', adapter: name === 'storefront' ? 'storefront_session' : 'not_configured',
    settings: { display_name: name, welcome: '欢迎咨询商城客服', handoff_threshold: 0.45 },
  }))
  let saved: unknown
  await page.route('**/api/admin/customer-service/channels', route => route.fulfill({ json: { items: channels } }))
  await page.route('**/api/admin/customer-service/channels/taobao', async route => {
    expect(route.request().method()).toBe('PUT')
    expect(route.request().headers()['x-csrf-token']).toBe('workspace-csrf')
    channels[1].settings = route.request().postDataJSON()
    saved = channels[1].settings
    await route.fulfill({ json: { name: 'taobao', connected: false, settings: channels[1].settings } })
  })
  await page.goto('/?view=admin&tab=support')
  await page.getByRole('button', { name: '渠道设置', exact: true }).click()
  await expect(page.locator('.support-channel')).toHaveCount(5)
  await expect(page.locator('.support-channel').getByText('已接入', { exact: true })).toHaveCount(1)
  await expect(page.locator('.support-channel').getByText('未接入', { exact: true })).toHaveCount(4)
  const taobao = page.locator('.support-channel').filter({ has: page.getByRole('heading', { name: '淘宝', exact: true }) })
  await taobao.getByLabel('展示名称').fill('淘宝服务入口')
  await taobao.getByLabel('欢迎语').fill('欢迎咨询商品与订单')
  await taobao.getByLabel('人工升级阈值（0.2–0.8）').fill('0.6')
  await taobao.getByRole('button', { name: '保存配置', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('淘宝渠道配置已保存')
  expect(saved).toEqual({ display_name: '淘宝服务入口', welcome: '欢迎咨询商品与订单', handoff_threshold: 0.6 })
  await expect(taobao.getByText('未接入', { exact: true })).toBeVisible()
  await expect(taobao).toContainText('适配器：未配置')
  await expect(taobao.getByRole('button', { name: '保存配置', exact: true })).toBeDisabled()
})

test('metrics show no-data dashes and actual numerators, denominators, and definitions', async ({ page }, testInfo) => {
  const windows: number[] = []
  const empty = { numerator: 0, denominator: 0, value: null }
  await page.route('**/api/admin/customer-service/metrics?*', route => {
    const days = Number(new URL(route.request().url()).searchParams.get('days'))
    windows.push(days)
    return route.fulfill({ json: {
      days, from: '2026-10-18T01:00:00Z', to: '2026-10-25T01:00:00Z',
      turns: days === 7 ? 0 : 6, consultations: days === 7 ? 0 : 3, routes: days === 7 ? {} : { faq: 4, order: 2 },
      resolution_rate: empty, satisfaction: empty, handoff_rate: days === 7 ? empty : { numerator: 1, denominator: 3, value: 1 / 3 },
      tool_success_rate: days === 7 ? empty : { numerator: 3, denominator: 4, value: 0.75 },
      retrieval_hit_rate: days === 7 ? empty : { numerator: 0, denominator: 2, value: 0 }, definitions,
    } })
  })
  await page.goto('/?view=admin&tab=support')
  await page.getByRole('button', { name: '服务指标', exact: true }).click()
  const metrics = page.locator('.support-metrics')
  const ratioTable = metrics.getByRole('table').first()
  await expect(ratioTable.locator('tbody tr')).toHaveCount(5)
  for (const row of await ratioTable.locator('tbody tr').all()) {
    await expect(row.getByRole('cell').nth(0)).toHaveText('—')
    await expect(row.getByRole('cell').nth(1)).toHaveText('0')
    await expect(row.getByRole('cell').nth(2)).toHaveText('0')
  }
  for (const definition of Object.values(definitions)) await expect(ratioTable).toContainText(definition)
  await expect(metrics).toContainText('暂无分流样本 —')
  await page.screenshot({ path: testInfo.outputPath('support-metrics-empty.png'), fullPage: true })
  await page.getByLabel('统计天数（1–30 天）').fill('3')
  await page.getByRole('button', { name: '应用范围', exact: true }).click()
  const handoff = ratioTable.getByRole('row').filter({ has: page.getByRole('rowheader', { name: '人工升级率', exact: true }) })
  await expect(handoff.getByRole('cell').nth(0)).toHaveText('33.3%')
  await expect(handoff.getByRole('cell').nth(1)).toHaveText('1')
  await expect(handoff.getByRole('cell').nth(2)).toHaveText('3')
  const retrieval = ratioTable.getByRole('row').filter({ has: page.getByRole('rowheader', { name: '知识检索命中率', exact: true }) })
  await expect(retrieval.getByRole('cell').nth(0)).toHaveText('0%')
  await expect(retrieval.getByRole('cell').nth(2)).toHaveText('2')
  await expect(metrics.locator('.support-route-table')).toContainText('faq')
  // StrictMode double-mounts issue the initial fetch twice in dev.
  expect([...new Set(windows)]).toEqual([7, 3])
})
