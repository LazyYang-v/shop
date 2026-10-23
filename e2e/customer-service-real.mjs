import assert from 'node:assert/strict'
import { chromium } from '@playwright/test'

const origin = process.env.SHOP_BROWSER_TEST_ORIGIN
assert.ok(/^http:\/\/127\.0\.0\.1:\d+$/.test(origin ?? ''))
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
    assert.deepEqual(listing.result.data.cards[0].product, expected)
    const compound = await ask('请问春日轻盈针织开衫的价格和库存？')
    assert.equal(compound.result.status, 'ok')
    assert.deepEqual(compound.result.data.cards[0].product, expected)
    await page.waitForFunction(() => document.querySelector('[role="log"]').textContent.split('可售库存：24').length >= 3)
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
  console.log('Chrome desktop/mobile anonymous sentences -> messages -> local MCP -> real fixture DB -> synthetic exchange + real ledger passed; unknown private text clarifies, cross-session pages denied. Real provider calls=0, money=0.')
} finally {
  await browser.close()
}
