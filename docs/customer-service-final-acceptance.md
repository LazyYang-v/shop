# 客服 #9：组合咨询与首版评测

日期：2026-10-24。工单：[LazyYang-v/docs#9](https://github.com/LazyYang-v/docs/issues/9)。集成分支：`integration/customer-service-ticket-9`，基线 `12f9346`。

**当前状态：实施与验收进行中；不能宣称真实商城首版通过。** 本票沿用 #4 已批准的合成政策范围：虚构商品、专用买家、合成政策与合成模型。真实商城政策、真实 WeKnora 产品接入和新增付费调用均未放行。依赖 #4、#5、#8 关闭不等于这些外部门槛解除。

## 验收范围与证据约定

浏览器 → 商城 API 为主要验收边界，事务使用真实隔离 PostgreSQL，后台回收通过既有扫描入口测试。用户已明确授权 #9 仅对 `127.0.0.1:55445/shop_test` 使用进程级 `SHOP_ALLOW_TEST_DATABASE_RESET=1` 运行既有夹具清理、API 与桌面/移动 Chrome，并发布真实结果；未授权开发库/演示库变更、新卷删除、共享 WeKnora 写入或新增付费请求。

下列固定问题和预期在 #9 最终运行前记录。它们是公开的开发/回归场景，不是独立盲测集，不用于推导生产准确率、用户解决率或成本收益。数据库生成的订单编号使用“本人的已选订单”“他人订单”描述；实际请求中的随机编号不进入公开证据。场景通过须有对应公共请求断言，不能只据代码存在、Mock 响应或既有十八项普通取消测试作结论。

证据分为：商城 API/真实 PostgreSQL；真实 Chrome/真实 API；真实 Chrome/模拟 API；独立离线参考；历史外部观察。矩阵中的“待本轮”不表示通过。历史结果只在注明版本/日期的单独记录中引用；不与本轮结果相加计算覆盖数。

## 六工具及独立协议能力

| 能力 | 固定输入与约束 | 预期事实来源 | 当前状态及验收入口 |
|---|---|---|---|
| list_products | “请问有哪些商品？”；分页仅由显式用户操作 | 当前批准 fixture 对应商品 API，最多 20 条，额外参数拒绝 | 既有实现；当前版本待整套 API/浏览器回归 |
| get_product | 完整 fixture 商品名称 + “价格和库存？”或用户点击详情 | 商城当前精确金额、库存与上架状态 | 既有确定性及合成模型路径；当前版本待回归 |
| search_policy | “演示商城多久发货？”及已批准完整主题；每轮最多 1 次 | 合成权威登记规范正文、来源、版本与区间；不采纳索引指令 | 合成路径既有实现；真实 WeKnora 关闭；当前版本待回归 |
| list_my_orders | “查询我的订单”；身份仅取认证会话，列表不能代替选择 | 当前买家订单候选，仅五字段 | 既有实现；当前版本待回归 |
| get_my_order | 浏览器明确选定的本人订单；模型不能自报选择 | 商城裁剪九字段及已保存物流；无地址电话 | 既有实现；组合场景待本轮验证 |
| propose_cancel | 明确已选、待支付、未超时订单；每轮最多 1 次 | 服务端操作摘要及独立确认卡；仅生成方案，不改订单 | 既有实现；组合场景待本轮验证 |
| 浏览器确认与核验 | 认证/CSRF/Origin/所有绑定；不注册给模型 | 操作证据与订单 API；核验可撤销凭据，不直接改订单 | #7/#8 既有实现；当前版本待回归 |
| 组合模型边界 | 受控组合意图；模型仅选择受限工具和引用代号 | 以上同一权限与分类额度，最终事实由服务端组装 | #9 实施中；不可宣称六工具真实提供方兼容性已验证 |

## 固定评测矩阵

### 黄金场景

| 编号 | 固定输入/前置状态 | 预期 | 实际结果 | 可复现证据入口 |
|---|---|---|---|---|
| G01 | 匿名：“请问有哪些商品？” | 仅 fixture 商品、精确价格/库存/上架状态及查询时间 | 待本轮 | `test_customer_service_consultations.py::test_anonymous_list_detail_and_consultation_expose_only_product_facts`；真实浏览器 |
| G02 | 匿名：“请问春日轻盈针织开衫的价格和库存？”；合成 exchange | 受控模型工具往返，最终事实与商品 API 一致；不发送原始商品名称/UUID | 待本轮 | 同文件 `test_anonymous_compound_question_completes_synthetic_tool_loop`；`test_customer_service_browser.py` |
| G03 | “演示商城多久发货？” | 显示“虚构演示政策（非真实商城政策）”、v2、来源和生效区间，不声称真实商城承诺 | 待本轮 | `test_customer_service_policy.py::test_policy_message_returns_citation_without_calling_a_model`；真实浏览器 |
| G04 | 买家：“查询我的订单”→点击一笔本人已发货订单 | 先候选后详情；已保存物流公司/运单号/发货时间与订单 API 一致，无实时轨迹及预计送达 | 待本轮 | `test_customer_service_orders.py::test_zero_one_and_multiple_orders_require_explicit_selection`、`test_order_detail_returns_only_trimmed_saved_facts`；真实浏览器 |
| G05 | 已明确选择本人待收货订单：“快递未到，我想退款” | 读取该单、展示已保存物流，说明无实时轨迹和退款接口；不生成不适用的取消方案、不声称退款受理 | 工作区定向 GREEN；初始 RED 为 needs_clarification 而非 ok；待合入回归与真实浏览器 | `test_customer_service_orders.py::test_delivery_refund_consultation_shows_selected_saved_logistics_and_capability_limits` |
| G06 | 已明确选择本人未超时待支付订单：同一组合诉求 | 只在条件满足时提出取消方案；明确取消不是退款，订单与库存签发前后不变，须按钮确认才执行 | 工作区定向 GREEN；初始 RED 未返回确认卡；待合入回归与真实浏览器 | 同文件 `test_delivery_refund_only_proposes_for_explicit_pending_unexpired_order`；原方案/确认回归 |
| G07 | 已选订单，政策检索故障；继续固定订单查询 | 政策不可用单独说明，固定订单查询独立成功且不调用模型/真实检索 | 工作区定向 GREEN；初始 RED 为 needs_clarification；待合入回归与真实浏览器 | 同文件 `test_composite_policy_outage_keeps_independent_selected_order_query`；预期 partial/policy_unavailable，附事实来源及查询时间 |

### 边界场景

| 编号 | 固定输入/前置状态 | 预期 | 实际结果 | 可复现证据入口 |
|---|---|---|---|---|
| B01 | 零、一、多单；未选单提出组合诉求或取消意图 | 不自动选择最近/唯一订单；无选择不能签发，先展示候选/要求选择 | 待本轮 | 订单 `test_zero_one_and_multiple_orders_require_explicit_selection`；方案 `test_selection_is_required_and_foreign_or_unknown_orders_are_unavailable`；#9 组合场景 |
| B02 | 已支付/已关闭订单或支付截止已到，提出方案/确认 | 拒绝不适用操作，不退款、不重复恢复库存 | 待本轮 | 方案 `test_non_pending_or_expired_orders_conflict_without_creating_an_operation`、`test_confirmation_rechecks_payment_deadline_before_order_cancellation` |
| B03 | 签发后 120 秒与支付截止取较早值；续期/后台暂停 | 凭据期限不延长，入口即时验期；扫描只转移仍待确认记录 | 待本轮 | 方案 `test_deadline_is_the_earlier_of_two_minutes_and_the_order_deadline`、`test_handoff_renewal_does_not_extend_the_confirmation_deadline`、`test_entry_and_periodic_expiry_only_move_pending_rows` |
| B04 | 未知取消结果持续处理中 | 2/4/8 秒后每 15 秒附抖动，5 分钟截止；保留编号，一次手动检查；不重放取消 | 待本轮 | Playwright `unclear cancellation confirmation reconciles without replay and offers one manual check` |
| B05 | 超过 10 页面、闲置 10 分钟、咨询 30 分钟/24 小时 | LRU 原子撤销旧资格；到期不可续活；新标签独立，合法交接只消费一次 | 待本轮 | 咨询 `test_lru_evicts_oldest_and_expiry_cannot_be_renewed`、`test_consultation_idle_and_absolute_deadlines`、`test_handoff_consumes_predecessor_and_renewal_keeps_token`；方案 LRU/交接测试 |
| B06 | 消息超过 16KiB/2000 码点、额外字段、非法页码、重复消息换正文 | 拒绝输入；同消息同正文持久重放不重复工具或签发 | 待本轮 | 咨询 `test_byte_and_codepoint_limits_and_csrf`、`test_uncontrolled_inputs_and_unknown_fields_rejected`、`test_list_select_and_dedupe_do_not_repeat_tools`；方案重放测试 |
| B07 | 撤回/未来/过期/删除残留政策或未知映射 | 无资格引用；conflict/no_match/unavailable 分别呈现 | 待本轮 | 政策 `test_withdrawn_expired_future_and_deleted_residue_are_never_current_basis`、`test_policy_message_keeps_no_match_conflict_and_unavailable_distinct` |
| B08 | 分类工具次数、重复规范参数、模型请求/用量/时间上限 | 不挪用分类额度，不换未批准工具；只展示已核验事实 | 待本轮 | 商品调用额度、模型四次/45 秒及共享预算回归；#9 模型组合预算场景 |

### 取消、恢复及运行回归

| 编号 | 固定输入/前置状态 | 预期 | 实际结果 | 可复现证据入口 |
|---|---|---|---|---|
| R01 | 用户确认、重复/并发确认 | 业务取消与证据同事务，最多恢复一次库存；重复返回已有证据 | 待本轮 | 方案 `test_confirmation_retry_returns_evidence_without_double_stock_restore`、`test_concurrent_confirmation_requests_cancel_once` |
| R02 | 业务写入失败并完整回滚 | 凭据、订单、库存及证据一起回滚；页面不自动核验，可由用户再确认 | 待本轮 | 方案 `test_confirmation_rolls_back_operation_order_and_stock_on_domain_failure`；Playwright `buyer confirmation cancels a pending order and verifies its execution evidence` |
| R03 | 确认已提交后响应丢失 | 仅核验，不重放；执行证据及独立订单 API 一致才显示本次成功 | 待本轮 | `test_customer_service_browser.py`→真实 Chrome；方案核验已执行证据测试 |
| R04 | 核验先到、迟到确认、重复核验 | 待确认置失效并撤销凭据；迟到确认 409、订单不变；重复证据稳定 | 待本轮 | 方案 `test_reconcile_pending_revokes_credential_and_late_confirmation_cannot_cancel`；真实浏览器及模拟 Playwright |
| R05 | 确认持锁与核验竞争/单独操作锁争用 | 最多等 1 秒；处理中不能推断回滚；释放后收敛到持久事实 | 待本轮 | 方案 `test_reconcile_row_lock_contention_returns_processing`、`test_reconcile_waits_for_confirmation_and_returns_committed_evidence` |
| R06 | 同一测试库重建应用后核验已终结操作 | 返回相同持久证据；页面重载不恢复旧确认权限 | 待本轮 | 方案 `test_reconcile_expiry_evidence_survives_application_restart`；真实浏览器重载检查 |
| R07 | 到期扫描与取消/支付竞争、重复扫描 | 状态和关闭原因正确，库存只恢复一次；原商城行为兼容 | 待本轮 | `test_order_lifecycle_api.py`、`test_order_expiry.py`；不得用这组替代客服端到端 |
| R08 | 日志删除失败、数据库不可用、目录权限变化 | 脱敏失败处理、后续扫描重试；不默默扩大日志或模型入口 | 待本轮 | `test_customer_service_maintenance.py`、`test_customer_service_guards.py` |
| R09 | 版本化 fixture 隔离恢复 | 旧会话/密码/咨询失效，新身份及商品查询恢复；历史证据不恢复 | 历史通过；本轮未重做 | [隔离演示恢复记录](../deploy/customer-service-demo/acceptance.md#验收记录)：2026-10-23 保守 124.32 秒，小于 30 分钟；仅证明当时镜像，不替代 #9 新部署恢复 |

R06 是同一隔离库上的应用重启，R09 是从版本化 fixture 创建新的隔离资源，两者不能互相替代。R09 没有备份或恢复运行期订单、聊天、会话和操作证据，RPO 无保证；124.32 秒的历史实测不是生产恢复 SLA。#9 本轮授权限于既有 `shop_test`，没有自动扩展为重建演示容器或创建新恢复卷。

### 授权与注入安全

| 编号 | 固定输入/前置状态 | 预期 | 实际结果 | 可复现证据入口 |
|---|---|---|---|---|
| S01 | 匿名查询本人订单或组合退款/物流诉求 | 401 登录引导，无订单或卡片；商品/合成政策仍独立可查 | 待本轮 | 订单 `test_anonymous_order_questions_require_login_without_order_data`；#9 组合场景 |
| S02 | 另一买家订单/操作、随机不存在编号、伪造 user_id/buyer_id | 同样拒绝资源；模型/请求不能替换服务端买家 | 待本轮 | 订单 `test_cross_buyer_selection_and_nonexistent_orders_are_uniformly_unavailable`；方案确认/核验绑定测试；#9 模型组合场景 |
| S03 | 退出、账号切换、会话到期或旧页面请求 | 旧授权失效；停止核验，不能跨会话复用 | 待本轮 | 订单 `test_invalid_session_logout_and_account_switch_invalidate_old_authorization`；方案跨买家及交接测试；Playwright 身份失效停止 |
| S04 | 缺 CSRF、错误 Origin、篡改页面/咨询/操作/凭据 | 拒绝且不改变订单；编号本身不是授权 | 待本轮 | 咨询 CSRF/绑定测试；方案 `test_confirmation_rejects_missing_csrf_wrong_origin_and_wrong_binding`、`test_reconcile_is_protected_and_bound_to_original_buyer_page` |
| S05 | 商品/索引含恶意指令，输入混合私人文本、额外身份或未批准工具 | 文案只当数据；本地澄清或受控拒绝；无越权执行/身份/秘密发送 | 待本轮 | 咨询 `test_unrecognized_private_text_never_enters_exchange`、`test_malformed_model_calls_fail_closed_without_replay`；政策注入测试；#9 组合场景 |
| S06 | 签发确认卡、模型工具结果、页面 DOM/URL/storage、安全日志 | 凭据仅一次浏览器内存，服务端只存哈希；模型无订单号、地址电话、运单号和秘密 | 待本轮 | 方案 `test_operation_is_bound_and_only_the_credential_hash_is_persisted`；真实浏览器哨兵及存储检查；#9 模型边界 |
| S07 | 自然语言“好的”、模型请求 confirm/reconcile/任意 URL/SQL | 不执行；确认/核验不在模型工具集，目标只能取服务端选择 | 待本轮 | 方案 `test_ordinary_chat_text_is_not_consent_and_proposal_logs_are_allowlisted`；MCP extras/mismatch；#9 模型组合测试 |
| S08 | 未批准账号/管理员、fixture 修改、共享额度存储故障 | 客服 fail-closed，无管理员代查或每进程静默回退 | 待本轮 | `test_customer_service_admission.py`、`test_customer_service_startup.py`、共享限流与模型预算故障测试 |

## 本轮执行记录

| 检查 | 实际结果 | 证据及限制 |
|---|---|---|
| 独立离线相关性参考 | 40/40 通过 | `python3 -I docs/policy-relevance-offline.py`；无外部调用，未回放临时真实候选文件；不代表商城 API 或生产质量 |
| 部署静态预检 | 通过 | `python3 -I deploy/customer-service-demo/preflight.py`；合成配置，默认 0 服务；未启动/更新容器 |
| 当前持久演示版本观察 | 仍是 #6 方案镜像 | 只读 `docker ps` 显示 `shop-customer-service-demo-api:20261023-cancel-proposal`，不是 #9 源码；本轮不将其当作新功能部署证明，不更新该环境 |
| 组合 API 的 TDD 定向循环 | 3 passed，11 deselected | 实施工作区报告三条新用例均先 RED 后 GREEN；只证明这三条公共 API 行为，最终分支仍需回归 |
| 当前分支 API/真实 PostgreSQL 完整回归 | 待运行 | 两个数据库 URL 都必须指向 `127.0.0.1:55445/shop_test`，只在测试进程启用既有清理授权 |
| 当前分支桌面与移动真实 Chrome | 待运行 | 不以桌面流程外加移动截图替代移动交互；记录具体组合流程和结果 |
| 当前分支 Playwright 页面模拟套件 | 待运行 | 与真实 API 证据分开，不证明事务或外部依赖 |
| 全后端类型检查基线 | 未通过：18 项既有诊断 | 在 #9 实现合入前运行 `uv run --project backend ty check backend/src/shop_api`；分布为 cancel 7、model_budget 3、model_transport 5、spend_guard 1、reconcile_demo_catalog 2；最终检查需区分新增诊断 |
| 构建、变更模块类型及差异检查 | 待运行 | 不把基线失败写成全项目类型检查通过 |
| 两轴代码审查 | 待运行 | Standards 与 Spec 分开报告，修复后补最终结果 |

## 本地重复验收入口

先确认测试容器实际目标为 loopback 的独立 `shop_test`、无其他并行数据库测试。只在当前终端设置两个数据库地址，应用导入所用 `SHOP_DATABASE_URL` 必须与 `SHOP_TEST_DATABASE_URL` 相同；密码从受控本地环境取得，不打印或提交：

```sh
export SHOP_TEST_DATABASE_URL='postgresql+psycopg://shop:<测试专用密码>@127.0.0.1:55445/shop_test'
SHOP_DATABASE_URL="$SHOP_TEST_DATABASE_URL" \
  SHOP_ALLOW_TEST_DATABASE_RESET=1 SHOP_RUN_BROWSER_TESTS=1 \
  uv run --project backend pytest backend/tests -q
```

完整后端测试调用真实 Chrome 时，夹具会在 loopback 临时端口启动商城 API 并挂载同源静态页，结束后回收服务。测试运行所需的合成 exchange 与政策由受信构造器/夹具提供，不启用真实外部调用，也无需启动持久演示容器。

页面模拟测试另在一个终端启动 `npm run dev -- --host 127.0.0.1 --strictPort`，在另一终端运行 `npm run test:e2e -- e2e/customer-service.spec.ts`；完成后停止本次启动的 Vite。Chrome 路径沿用 `playwright.config.ts`。构建使用 `npm run build`。若环境缺少 Chrome、Node 或专用测试库，应记为阻塞，不能跳过后声称完整通过。

## 工单验收状态与未完成项

| #9 条目 | 当前交付状态 | 放行限制 |
|---|---|---|
| 快递未到且想退款的组合演示 | 实施中 | 只适用取消方案；无退款、实时轨迹或人工受理能力 |
| 政策故障与独立订单、同权限模型组合 | 实施中 | 六工具模型路径需合成协议及权限/预算测试；真实提供方兼容性另计 |
| 固定黄金/边界/回归/安全输入与证据 | 矩阵已固定，运行待补 | 不将计划或旧普通取消用例标成客服全链路通过 |
| 实现/验证/阻塞分开记录 | 本文及各切片记录 | 尚未执行的行保持待验证；不填写未测解决率/成本 |
| 全部 WeKnora 证据和完整首版 | [能力矩阵已整理](customer-service-weknora-acceptance.md)，真实入口阻塞 | 真实政策、适配器、权限复核、依赖故障/独立问题集及外部保留条件未满足；不宣称首版通过 |

当前可交付目标是可重复的合成组合演示和可审计评测。真实商城首版仍受 [WeKnora 放行阻塞](customer-service-weknora-acceptance.md#真实首版放行阻塞)约束；本票最终状态应随实际验收结果记录，不能为了关闭工单把这些门槛改成已完成。
