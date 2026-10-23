# 客服 #8 取消结果核验验收记录

关联：[LazyYang-v/docs#8](https://github.com/LazyYang-v/docs/issues/8)。更新：2026-10-24。

状态：当前版本完整客服 Playwright 套件、真实 Chrome → 商城 API → 隔离 PostgreSQL 验收及相关 API 回归均通过。核心实现提交为 `73f19629af03318b62206464cc8dd6064d6db802`；浏览器验收补充提交为 `9680b4b`，位于 `integration/customer-service-ticket-8`。

## 实现与测试边界

- 核验接口校验认证会话、CSRF、来源及买家、页面、咨询和操作绑定，与确认使用同一操作记录排他锁。锁等待限制为一秒；待确认操作条件失效并撤销凭据，终态返回持久证据，迟到确认不能取消订单。
- 浏览器只在确认结果未知或处理中时核验，不重放取消；明确回滚允许买家在凭据有效期内重新确认。自动轮询按二、四、八秒及后续十五秒加入抖动，五分钟停止并保留一次手动检查；终态、身份或页面失效时停止。成功提示要求执行证据与独立订单 API 状态一致。
- `e2e/customer-service.spec.ts` 模拟 API 响应，验证页面行为、请求绑定、轮询、截止、停止及单次手动检查。新增用例覆盖核验先完成后的失效提示、迟到确认和重复核验响应；模拟响应本身不证明真实事务或证据持久性。
- `backend/tests/test_customer_service_browser.py` 通过真实地址、购物车和下单 API 准备待支付订单，使用既有隔离数据库夹具和安全检查。
- `e2e/customer-service-real.mjs` 保留真实确认提交后丢响应的场景；另一笔订单先拦截确认请求，让真实核验接口撤销凭据，再向真实后端发送迟到确认。验证重复核验证据一致、迟到确认 409、订单仍待支付及页面重载后状态不变。核验响应等待器在点击前注册；重复核验在原页面绑定有效时完成。
- 锁争用、确认与核验竞争、应用重启后的持久证据及到期清理通过真实 PostgreSQL API 用例验证。页面重载与应用重启分别记录；真实浏览器脚本覆盖页面重载，应用重启由 API 测试覆盖。

## 当前版本验证结果

| 检查 | 结果 | 范围 |
|---|---|---|
| 完整客服 Playwright 套件 | 25 passed，24.9 秒 | `npm run test:e2e -- e2e/customer-service.spec.ts`；真实 Chrome、模拟 API |
| PostgreSQL API 与真实浏览器验收 | 50 passed，22.37 秒 | `test_customer_service_cancel_proposal.py`、`test_customer_service_maintenance.py`、`test_order_expiry.py`、`test_customer_service_browser.py`；设置 `SHOP_RUN_BROWSER_TESTS=1`，真实浏览器用例执行通过 |
| 前端类型检查与构建 | 通过 | `npm run build` |
| 真实浏览器脚本语法 | 通过 | `node --check e2e/customer-service-real.mjs` |
| Python 浏览器夹具语法 | 通过 | 标准库 AST 解析 |
| 差异格式检查 | 通过 | `git diff --check`、提交差异检查 |
| 浏览器验收补充独立复核 | 未发现具体缺陷 | 只读检查三个测试文件及相关接口、页面和会话逻辑 |

后端测试出现两条依赖弃用警告：Starlette TestClient 的 httpx 用法及 Alembic 配置缺少 `path_separator`。无失败或跳过。首次直接 pytest 调用因导入应用时未设置 `SHOP_DATABASE_URL` 而在加载用例前停止；将应用和测试两个数据库地址都设为同一隔离测试库后，上述四份测试全部通过。

## 数据库及外部调用范围

用户明确授权本次对 `127.0.0.1:55445/shop_test` 使用进程级 `SHOP_ALLOW_TEST_DATABASE_RESET=1` 运行既有夹具清理、API 和真实 Chrome 验收，并发布 GitHub 验证结果。此前自动审批对仓库外 runner 和测试清理的阻塞已通过明确授权及仓库正式 pytest 入口解决；未复制或执行仓库外 runner。

测试仅连接既有 `shop-portfolio-test-postgres` 容器及独立卷 `shop_shop-portfolio-test-postgres-data`；应用与测试数据库地址均指向 `127.0.0.1:55445/shop_test`。数据库名称与清理授权安全检查保持启用，沿用既有夹具的迁移、种子准备和测试数据清理范围。没有访问开发库或演示库、删除数据库卷、扩展清理逻辑，或向 `.env`、源码、持久配置写入清理开关。

真实浏览器验收使用合成模型交换和合成政策；真实模型调用 0、WeKnora 请求 0、费用 0。临时前端服务器已停止；真实浏览器夹具负责关闭其 API 服务及浏览器。
