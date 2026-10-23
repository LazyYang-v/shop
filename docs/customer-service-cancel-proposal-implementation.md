# 客服 #6 取消确认方案实施记录

日期：2026-10-23。状态：**本地源码、隔离测试数据库、真实 Chrome 与前端模拟 API 回归均已通过；未部署隔离演示容器，#6 待验收关闭。** 关联：GitHub `LazyYang-v/docs#6`，前置 [#5](customer-service-order-implementation.md) 已关闭。范围仍为虚构演示数据与两名受控演示买家。

## 实现边界

- **只提出方案，不执行取消**：本切片新增 `propose_cancel` 模型工具与浏览器确认卡，只创建操作记录；订单状态、库存、关闭原因均不变。未注册 `/cancel/confirm`、`/cancel/reconcile` 或任何模型执行/核验工具。
- **服务端明确选择**：`/messages` 中用户点击候选订单产生的 `selected_order_id` 先由服务端校验买家归属并记录到页面实例；`propose_cancel` 必须匹配该页面记录，模型不能自报选择。缺少选择、选择他人订单、选择未知订单或选择已变化均拒绝。
- **一次性凭据**：签发时用 `secrets.token_urlsafe(32)` 生成 43 字符明文，服务端只持久化 SHA-256 哈希。明文仅经顶层 `confirmation_card.confirmation_token` 返回浏览器，并只保存在页面 JavaScript 内存；不进入 MCP 工具结果、聊天 `data`、安全日志、URL、`localStorage` 或 `sessionStorage`。重放已有 `client_message_id` 不重新签发，返回已有操作摘要与 `card_unavailable`，卡片不含凭据。
- **模型可见范围**：MCP 结果只含操作编号、状态、商品摘要、金额、币种与期限；原始订单号不进入工具结果，确认卡的 `order_number` 由服务端依据页面选择记录补齐。工具结果严格校验字段集合，任何额外字段或缺失字段均视为依赖不可用。
- **期限**：确认期限取“签发后 120 秒”和“订单支付截止”中的较早者。入口即时检查订单状态及到期；30 秒维护任务按 `expires_at <= now` 条件置失效，只改仍为 `pending` 的记录，不覆盖已执行/已拒绝/已失效终态。
- **撤销与清理**：页面选择变化、新方案签发、有效交接消费、页面过期/LRU 淘汰及咨询清理都会条件撤销该页面的待确认凭据；已消费或终态记录不复活。续期交接标识只延长交接期限，不延长确认期限。
- **限流**：方案签发每买家 5 次/分钟；显式订单选择仍计入每买家 10 次/分钟探测额度；会话 20 次/分钟与每 IP 60 次/分钟沿用既有额度。
- **数据库**：迁移 `0021_cs_cancel_proposals` 为页面增加服务端选择字段，并创建 `customer_service_cancel_operations`；约束保证待确认记录必须有凭据哈希、终态必须清空哈希且写入终态时间，部分唯一索引保证同一页面最多一个待确认方案。
- **浏览器**：待付款订单详情显示“申请取消订单”。确认卡展示订单号、状态、金额与确认期限，并固定展示“取消后将恢复商品库存；操作不可撤销；购物车不会恢复。”；确认按钮保持禁用并标注“确认执行尚未开放”。卡片不持久化，刷新后只保留允许的交接标识，旧卡不再显示。前端严格校验卡片字段、UUID、金额、币种与 43 字符凭据格式。
- **安全日志**：`propose_cancel` 与 `state_conflict` 加入安全日志白名单，日志字段仍只含请求标识、工具、错误、耗时、计数与时间。

## 测试证据

| 项目 | 命令/入口 | 实际结果 |
|---|---|---|
| 新增方案 API/边界 | `uv run --project backend python -I /tmp/shop-phase-a-tests.py backend/tests/test_customer_service_cancel_proposal.py -q` | 14 passed；覆盖签发与不写订单、凭据哈希与绑定、重放、缺失/他人/未知/已变化选择、非待付款/已到期订单、期限取较早者、条件清理、限流、新方案与选择变化撤销、交接/清理/LRU 撤销、续期不延长期限、MCP 仅暴露 `propose_cancel`、额外参数/返回字段拒绝、未注册确认/核验路由、自然语言同意不执行、日志白名单 |
| 完整后端回归（含真实 Chrome） | `SHOP_RUN_BROWSER_TESTS=1 uv run --project backend python -I /tmp/shop-phase-a-tests.py backend/tests -q` | **342 passed**，2 项依赖弃用警告，49.41s |
| 真实 Chrome 方案链路 | 同上 `test_customer_service_browser.py` | 1 passed；真实 DB 两笔订单候选、待收货详情、待付款详情、固定触发文字签发、卡片后果与禁用按钮、凭据/操作编号不进入 DOM/日志/URL/浏览器存储、刷新后卡片消失且交接标识可用、交接后列表不返回旧卡 |
| 前端 Playwright | `npx playwright test e2e/customer-service.spec.ts` | 19 passed；新增待付款订单申请取消方案、卡片展示、禁用确认、请求正文、凭据与操作编号不写入浏览器存储 |
| 前端构建 | `npm run build` | 通过 |
| 类型检查（变更模块） | `uv run --project backend ty check backend/src/shop_api/customer_service_cancel.py backend/src/shop_api/customer_service_consultations.py backend/src/shop_api/customer_service_maintenance.py backend/src/shop_api/customer_service_product_mcp.py backend/src/shop_api/customer_service.py` | 0 diagnostics |
| 付费/外部调用 | — | **0 次模型调用、0 次 WeKnora 请求、0 元**；方案路径为确定性流程，不调用模型 transport |

本地测试仅使用 `127.0.0.1:55445/shop_test` 及隔离真实 Chrome；`SHOP_ALLOW_TEST_DATABASE_RESET=1` 只在测试子进程设置。未部署、未重启或写入演示容器/开发库，也未运行付费模型或 WeKnora 请求。

## Acceptance criteria 对照

1. **展示订单号、状态与后果，只创建操作记录** — 确认卡与浏览器断言覆盖订单号、待付款、金额、期限及三条固定后果；数据库测试确认订单与库存不变。
2. **编号/一次性凭据绑定买家、会话、咨询、页面、订单与动作，期限取两分钟与支付截止较早者** — 操作记录含全部绑定键及动作；替换选择、他人订单、已到期订单均拒绝；期限边界与较短支付截止有测试。
3. **只存哈希，明文经独立前端响应进入内存，不进模型/聊天/日志/URL/浏览器持久存储；自然语言同意不执行** — 工具结果不含凭据或原始订单号；真实 Chrome 与 Playwright 检查 DOM、日志、URL、存储；普通“好的”文本不创建操作。
4. **交接标识仅 sessionStorage、90 秒有效、30 秒续期、同页一个在途、恢复前台立即续期** — 既有交接实现保持不变；新增测试验证续期不延长确认期限，真实 Chrome 验证刷新后的交接标识不含凭据。
5. **有效交接撤销前驱未执行凭据，过期/丢失只新建实例，不宣称关闭页面即时撤销** — 交接消费与页面清理条件撤销待确认记录；页面删除不依赖即时撤销承诺，旧凭据由期限与会话校验兜底。
6. **实例上限、周期清理、入口即时检查、重启恢复且不覆盖终态** — 页面 LRU 与 30 秒清理撤销待确认记录；维护任务条件置失效；重启后任务重新注册；终态不被覆盖有测试。
7. **浏览器及真实数据库覆盖签发、篡改、刷新、到期、续期/交接竞争与实例限制；实现模型工具但不注册确认执行或核验** — 14 项 API/数据库测试与真实 Chrome 覆盖上述路径；MCP 仅暴露 `propose_cancel`，确认与核验路由不存在。

## 限制

- 未开放确认执行、结果核验或任何订单写操作；确认按钮为占位禁用状态。
- 未部署到隔离演示容器，也未进行容器 API/浏览器/日志验收；不能声称演示环境已可用。
- 未进行跨进程 MySQL/PostgreSQL 故障注入或提交/响应丢失演练；相关结果核验属于后续工单。
- 演示仍以订单 UUID 作为可展示订单号。

## 结论

取消确认方案在本地与隔离测试范围内完成，七条验收标准均有对应实现与测试证据；确认执行、核验及真实部署仍不在本票范围。`LazyYang-v/docs#6` 尚未关闭，等待明确验收授权。
