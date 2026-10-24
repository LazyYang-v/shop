# 客服 #9：组合咨询与首版评测

日期：2026-10-24。工单：[LazyYang-v/docs#9](https://github.com/LazyYang-v/docs/issues/9)。集成分支：`integration/customer-service-ticket-9`，基线 `12f9346`，完整回归受测代码 `a4478a6`，后续隔离部署镜像源码 `4e43485`（产品代码相同）。

**当前状态：合成组合实现及审查修复已合入，完整后端/API/真实 Chrome 回归 399 项通过，页面模拟套件 28 项通过；真实商城首版仍阻塞，#9 保持 OPEN。** 本票沿用 #4 已批准的合成政策范围：虚构商品、专用买家、合成政策与合成模型。真实商城政策、真实 WeKnora 产品接入和新增付费调用均未放行。依赖 #4、#5、#8 关闭不等于这些外部门槛解除。

## 验收范围与证据约定

浏览器 → 商城 API 为主要验收边界，事务使用真实隔离 PostgreSQL，后台回收通过既有扫描入口测试。初次授权仅对 `127.0.0.1:55445/shop_test` 使用进程级 `SHOP_ALLOW_TEST_DATABASE_RESET=1` 运行既有夹具清理、API 与桌面/移动 Chrome，并发布真实结果。随后用户明确授权升级 `shop-customer-service-demo`、通过商城 API 准备虚构订单、创建独立恢复项目及私有凭据，并单独批准恢复网络和临时政策不可用/恢复；具体范围及实绩见[部署恢复记录](../deploy/customer-service-demo/ticket-9-acceptance.md)。未授权开发库变更、旧卷删除、共享 WeKnora 写入或新增付费请求。

下列固定问题和预期在 #9 最终运行前记录。它们是公开的开发/回归场景，不是独立盲测集，不用于推导生产准确率、用户解决率或成本收益。数据库生成的订单编号使用“本人的已选订单”“他人订单”描述；实际请求中的随机编号不进入公开证据。场景通过须有对应公共请求断言，不能只据代码存在、Mock 响应或既有十八项普通取消测试作结论。

证据分为：商城 API/真实 PostgreSQL；真实 Chrome/真实 API；真实 Chrome/模拟 API；独立离线参考；历史外部观察。以下 32 个场景中，31 个在完整回归代码上由对应 API 或页面用例验证；后续在同一产品代码的隔离镜像上补齐 R09 新卷恢复，32 个场景均有当前合成范围的实际证据。399 是完整后端测试参数项数，28 是另行执行的页面参数项数，不是场景数；二者不相加计算端到端覆盖。Mock 页面证据不证明真实事务或外部依赖。

## 六工具及独立协议能力

| 能力 | 固定输入与约束 | 预期事实来源 | 当前状态及验收入口 |
|---|---|---|---|
| list_products | “请问有哪些商品？”；分页仅由显式用户操作 | 当前批准 fixture 对应商品 API，最多 20 条，额外参数拒绝 | 已实现；最终 API、合成六工具往返及真实 Chrome 通过 |
| get_product | 完整 fixture 商品名称 + “价格和库存？”或用户点击详情 | 商城当前精确金额、库存与上架状态 | 已实现；确定性、合成模型 API 及真实 Chrome 通过 |
| search_policy | “演示商城多久发货？”及已批准完整主题；每轮最多 1 次 | 合成权威登记规范正文、来源、版本与区间；不采纳索引指令 | 合成 API、撤回/冲突/不可用及浏览器通过；真实 WeKnora 关闭 |
| list_my_orders | “查询我的订单”；身份仅取认证会话，列表不能代替选择 | 当前买家订单候选，仅五字段 | 已实现；最终 API、合成模型及真实 Chrome 通过 |
| get_my_order | 浏览器明确选定的本人订单；模型不能自报选择 | 商城裁剪九字段及已保存物流；无地址电话 | 已实现；最终选单/越权/组合 API 及真实 Chrome 通过 |
| propose_cancel | 明确已选、待支付、未超时订单；每轮最多 1 次 | 服务端操作摘要及独立确认卡；仅生成方案，不改订单 | 已实现；适用条件、合成组合、失败撤销凭据及真实 Chrome 通过 |
| 浏览器确认与核验 | 认证/CSRF/Origin/所有绑定；不注册给模型 | 操作证据与订单 API；核验可撤销凭据，不直接改订单 | #7/#8 已实现；最终事务、竞争、重启读取及浏览器回归通过 |
| 组合模型边界 | 受控整句“快递未到且想退款”/“快递未到，我想退款”，或分号连接 2–4 个完整批准子句；模型仅选择受限工具和引用代号 | 以上同一权限与分类额度，最终事实由服务端组装 | #9 已实现并通过合成验证；仅受信 `create_app(synthetic_consultation_exchange=...)` 可注入合成 exchange，未注入时确定性执行；六工具真实提供方兼容性未验证 |

## 固定评测矩阵

### 黄金场景

| 编号 | 固定输入/前置状态 | 预期 | 实际结果 | 可复现证据入口 |
|---|---|---|---|---|
| G01 | 匿名：“请问有哪些商品？” | 仅 fixture 商品、精确价格/库存/上架状态及查询时间 | 通过：API 与桌面/移动真实 Chrome 返回批准商品事实 | `test_customer_service_consultations.py::test_anonymous_list_detail_and_consultation_expose_only_product_facts`；真实浏览器 |
| G02 | 匿名：“请问春日轻盈针织开衫的价格和库存？”；合成 exchange | 受控模型工具往返，最终事实与商品 API 一致；不发送原始商品名称/UUID | 通过：合成工具循环及两端真实 Chrome；哨兵断言无名称/UUID/私人数据外发 | 同文件 `test_anonymous_compound_question_completes_synthetic_tool_loop`；`test_customer_service_browser.py` |
| G03 | “演示商城多久发货？” | 显示“虚构演示政策（非真实商城政策）”、v2、来源和生效区间，不声称真实商城承诺 | 通过：合成登记引用与规范正文一致；API 和真实 Chrome 展示合成标识 | `test_customer_service_policy.py::test_policy_message_returns_citation_without_calling_a_model`；真实浏览器 |
| G04 | 买家：“查询我的订单”→点击一笔本人已发货订单 | 先候选后详情；已保存物流公司/运单号/发货时间与订单 API 一致，无实时轨迹及预计送达 | 通过：API 验证裁剪字段；两端真实 Chrome 先列表、后显式选择 | `test_customer_service_orders.py::test_zero_one_and_multiple_orders_require_explicit_selection`、`test_order_detail_returns_only_trimmed_saved_facts`；真实浏览器 |
| G05 | 已明确选择本人待收货订单：“快递未到，我想退款”或“快递未到且想退款” | 读取该单、展示已保存物流，说明无实时轨迹和退款接口；不生成不适用的取消方案、不声称退款受理 | 通过：两种表述的 API 参数均通过；固定句在桌面/移动真实 Chrome 完成，页面来源展示通过 | `test_customer_service_orders.py::test_delivery_refund_consultation_shows_selected_saved_logistics_and_capability_limits`；Playwright `selected buyer order receives composite refund limits and per-item partial sources` |
| G06 | 已明确选择本人未超时待支付订单：同一组合诉求 | 只在条件满足时提出取消方案；明确取消不是退款，订单与库存签发前后不变，须按钮确认才执行 | 通过：API 检查签发不改订单/库存及过期拒绝；两端真实 Chrome 签发、用户确认和丢失响应后核验成功 | 同文件 `test_delivery_refund_only_proposes_for_explicit_pending_unexpired_order`；真实 `test_customer_service_browser.py`；方案/确认回归 |
| G07 | 已选订单，政策检索故障；继续固定订单查询 | 政策不可用单独说明，固定订单查询独立成功且不调用模型/真实检索 | 通过：API 返回 partial/policy_unavailable，保留订单来源/时间；两端真实 Chrome 注入合成索引故障后固定查单仍成功 | 同文件 `test_composite_policy_outage_keeps_independent_selected_order_query`；真实与模拟浏览器 |

### 边界场景

| 编号 | 固定输入/前置状态 | 预期 | 实际结果 | 可复现证据入口 |
|---|---|---|---|---|
| B01 | 零、一、多单；未选单提出组合诉求或取消意图 | 不自动选择最近/唯一订单；无选择不能签发，先展示候选/要求选择 | 通过：API 各数量均要求明确选择；合成模型无选择请求详情被拒，不签发 | 订单 `test_zero_one_and_multiple_orders_require_explicit_selection`；方案 `test_selection_is_required_and_foreign_or_unknown_orders_are_unavailable`；#9 no_selection 参数 |
| B02 | 已支付/已关闭订单或支付截止已到，提出方案/确认 | 拒绝不适用操作，不退款、不重复恢复库存 | 通过：API 对非待支付及过期状态拒绝；组合不产生不适用确认卡 | 方案 `test_non_pending_or_expired_orders_conflict_without_creating_an_operation`、`test_confirmation_rechecks_payment_deadline_before_order_cancellation` |
| B03 | 签发后 120 秒与支付截止取较早值；续期/后台暂停 | 凭据期限不延长，入口即时验期；扫描只转移仍待确认记录 | 通过：API 覆盖两期限、续期及重复到期扫描；页面过期卡不可用 | 方案 `test_deadline_is_the_earlier_of_two_minutes_and_the_order_deadline`、`test_handoff_renewal_does_not_extend_the_confirmation_deadline`、`test_entry_and_periodic_expiry_only_move_pending_rows` |
| B04 | 未知取消结果持续处理中 | 2/4/8 秒后每 15 秒附抖动，5 分钟截止；保留编号，一次手动检查；不重放取消 | 通过：Mock Chrome 时钟验证轮询和一次手动检查；真实丢失响应另见 R03 | Playwright `unclear cancellation confirmation reconciles without replay and offers one manual check` |
| B05 | 超过 10 页面、闲置 10 分钟、咨询 30 分钟/24 小时 | LRU 原子撤销旧资格；到期不可续活；新标签独立，合法交接只消费一次 | 通过：API 覆盖 LRU、闲置/绝对期限、交接与竞争；Mock Chrome 覆盖重载/续期 | 咨询 `test_lru_evicts_oldest_and_expiry_cannot_be_renewed`、`test_consultation_idle_and_absolute_deadlines`、`test_handoff_consumes_predecessor_and_renewal_keeps_token`；方案 LRU/交接测试 |
| B06 | 消息超过 16KiB/2000 码点、额外字段、非法页码、重复消息换正文 | 拒绝输入；同消息同正文持久重放不重复工具或签发 | 通过：API 拒绝越界/额外字段；组合成功、失败及超时结果均有持久重放断言 | 咨询 `test_byte_and_codepoint_limits_and_csrf`、`test_uncontrolled_inputs_and_unknown_fields_rejected`、`test_list_select_and_dedupe_do_not_repeat_tools`；方案与组合重放测试 |
| B07 | 撤回/未来/过期/删除残留政策或未知映射 | 无资格引用；conflict/no_match/unavailable 分别呈现 | 通过：合成 API 拒绝无资格引用并区分三类结果；组合交付前撤回也移除引用 | 政策 `test_withdrawn_expired_future_and_deleted_residue_are_never_current_basis`、`test_policy_message_keeps_no_match_conflict_and_unavailable_distinct`；组合 withdraw 参数 |
| B08 | 分类工具次数、重复规范参数、模型请求/用量/时间上限 | 不挪用分类额度，不换未批准工具；只展示已核验事实 | 通过：10 个组合失败参数、重试分类/总额及超时修复回归；有事实返回持久 partial，无事实 503，失败撤销方案凭据 | `test_customer_service_orders.py::test_synthetic_composition_stops_safely_with_verified_partial_results`（duplicate/execute/extra/withdraw/unfinished/budget/request_limit/no_selection/identity/private_text）；修复入口见下表及审查记录 |

### 取消、恢复及运行回归

| 编号 | 固定输入/前置状态 | 预期 | 实际结果 | 可复现证据入口 |
|---|---|---|---|---|
| R01 | 用户确认、重复/并发确认 | 业务取消与证据同事务，最多恢复一次库存；重复返回已有证据 | 通过：真实 PostgreSQL API 验证重复与并发事务，库存只恢复一次 | 方案 `test_confirmation_retry_returns_evidence_without_double_stock_restore`、`test_concurrent_confirmation_requests_cancel_once` |
| R02 | 业务写入失败并完整回滚 | 凭据、订单、库存及证据一起回滚；页面不自动核验，可由用户再确认 | 通过：API 验证完整回滚；Mock Chrome 先回滚后由用户再确认，终态替换旧说明 | 方案 `test_confirmation_rolls_back_operation_order_and_stock_on_domain_failure`；Playwright `buyer confirmation handles ${confirmationResponse} responses and verifies its execution evidence`（executed/lost/processing） |
| R03 | 确认已提交后响应丢失 | 仅核验，不重放；执行证据及独立订单 API 一致才显示本次成功 | 通过：两端真实 Chrome 在真实提交后丢失响应，仅确认一次；核验和订单 API 一致，旧未知说明消失 | `test_customer_service_browser.py`→真实 Chrome；方案核验已执行证据测试；Mock lost 参数 |
| R04 | 核验先到、迟到确认、重复核验 | 待确认置失效并撤销凭据；迟到确认 409、订单不变；重复证据稳定 | 通过：API、真实及 Mock Chrome 均验证迟到确认拒绝和稳定证据 | 方案 `test_reconcile_pending_revokes_credential_and_late_confirmation_cannot_cancel`；真实浏览器及模拟 Playwright |
| R05 | 确认持锁与核验竞争/单独操作锁争用 | 最多等 1 秒；处理中不能推断回滚；释放后收敛到持久事实 | 通过：真实 PostgreSQL API 覆盖锁争用与提交后收敛；Mock processing 参数核验终态 | 方案 `test_reconcile_row_lock_contention_returns_processing`、`test_reconcile_waits_for_confirmation_and_returns_committed_evidence` |
| R06 | 同一测试库重建应用后核验已终结操作 | 返回相同持久证据；页面重载不恢复旧确认权限 | 通过：API 跨应用读取相同证据及组合超时结果；真实 Chrome 重载后旧卡不可恢复 | 方案 `test_reconcile_expiry_evidence_survives_application_restart`；组合超时持久重放；真实浏览器重载检查 |
| R07 | 到期扫描与取消/支付竞争、重复扫描 | 状态和关闭原因正确，库存只恢复一次；原商城行为兼容 | 通过：原商城 API 与扫描入口在完整后端回归中通过；此项与客服端到端分开 | `test_order_lifecycle_api.py`、`test_order_expiry.py`；不得用这组替代客服端到端 |
| R08 | 日志删除失败、数据库不可用、目录权限变化 | 脱敏失败处理、后续扫描重试；不默默扩大日志或模型入口 | 通过：维护/守卫故障注入及公共 API 拒绝行为符合预期；未向真实外部依赖注入故障 | `test_customer_service_maintenance.py`、`test_customer_service_guards.py` |
| R09 | 版本化 fixture 隔离恢复 | 旧会话/密码/咨询失效，新身份及商品查询恢复；历史证据不恢复 | 通过：#9 镜像在新卷恢复，两端 Chrome 验证旧资格失效、新身份及 fixture 查询；478.269 秒含故障与确认等待，小于 30 分钟 | [#9 部署恢复记录](../deploy/customer-service-demo/ticket-9-acceptance.md#恢复计时与边界)；`e2e/customer-service-deployment.mjs` recovery 模式。旧 124.32 秒仅保留为历史事实 |

R06 是同一隔离库上的应用重启，R09 是从版本化 fixture 创建新的隔离资源，两者不能互相替代。R09 没有备份或恢复运行期订单、聊天、会话和操作证据，RPO 无保证；旧 124.32 秒与当前 478.269 秒均不是生产恢复 SLA。此次恢复使用用户另行明确批准的新项目与新卷，原演示及历史恢复卷保留。

### 授权与注入安全

| 编号 | 固定输入/前置状态 | 预期 | 实际结果 | 可复现证据入口 |
|---|---|---|---|---|
| S01 | 匿名查询本人订单或组合退款/物流诉求 | 401 登录引导，无订单或卡片；商品/合成政策仍独立可查 | 通过：API 对匿名订单及两种组合表述要求登录；页面显示登录引导 | 订单 `test_anonymous_order_questions_require_login_without_order_data`；#9 物流退款参数；Mock 页面 |
| S02 | 另一买家订单/操作、随机不存在编号、伪造 user_id/buyer_id | 同样拒绝资源；模型/请求不能替换服务端买家 | 通过：API 统一拒绝他人/不存在订单和错误绑定；合成模型额外身份参数被拒 | 订单 `test_cross_buyer_selection_and_nonexistent_orders_are_uniformly_unavailable`；方案确认/核验绑定测试；#9 extra 参数 |
| S03 | 退出、账号切换、会话到期或旧页面请求 | 旧授权失效；停止核验，不能跨会话复用 | 通过：API、真实及 Mock Chrome 验证失效边界；组合超时交付重新校验会话/买家/页面/选择，不泄露已有私人事实 | 订单 `test_invalid_session_logout_and_account_switch_invalidate_old_authorization`；`test_composite_timeout_revalidates_current_access_before_partial_delivery`；方案及浏览器 |
| S04 | 缺 CSRF、错误 Origin、篡改页面/咨询/操作/凭据 | 拒绝且不改变订单；编号本身不是授权 | 通过：API 拒绝 CSRF、Origin、所有绑定及凭据篡改；Mock 页面拒绝篡改卡 | 咨询 CSRF/绑定测试；方案 `test_confirmation_rejects_missing_csrf_wrong_origin_and_wrong_binding`、`test_reconcile_is_protected_and_bound_to_original_buyer_page` |
| S05 | 商品/索引含恶意指令，输入混合私人文本、额外身份或未批准工具 | 文案只当数据；本地澄清或受控拒绝；无越权执行/身份/秘密发送 | 通过：API 与合成 exchange 验证注入无效、未知私人子句不被剔除后发送、索引指令不进回答 | 咨询 `test_unrecognized_private_text_never_enters_exchange`、`test_malformed_model_calls_fail_closed_without_replay`；政策注入测试；#9 private_text/extra/execute 参数 |
| S06 | 签发确认卡、模型工具结果、页面 DOM/URL/storage、安全日志 | 凭据仅一次浏览器内存，服务端只存哈希；模型无订单号、地址电话、运单号和秘密 | 通过：六工具成功 API 检查完整裁剪；两端真实 Chrome 检查 DOM/storage，模型和日志哨兵均未出现 | `test_customer_service_orders.py::test_synthetic_composition_uses_six_tools_without_private_data_or_execution`；方案哈希持久化测试、真实浏览器哨兵及存储检查 |
| S07 | 自然语言“好的”、模型请求 confirm/reconcile/任意 URL/SQL | 不执行；确认/核验不在模型工具集，目标只能取服务端选择 | 通过：API/协议拒绝未批准工具与参数；合成 execute 参数不执行取消，订单保持待支付 | 方案 `test_ordinary_chat_text_is_not_consent_and_proposal_logs_are_allowlisted`；MCP extras/mismatch；#9 模型组合测试 |
| S08 | 未批准账号/管理员、fixture 修改、共享额度存储故障 | 客服 fail-closed，无管理员代查或每进程静默回退 | 通过：准入、启动、共享限流/模型预算故障测试；故障拒绝行为在 API 观察 | `test_customer_service_admission.py`、`test_customer_service_startup.py`、共享限流与模型预算故障测试 |

## 本轮执行记录

| 检查 | 实际结果 | 证据及限制 |
|---|---|---|
| 最终 API/真实 PostgreSQL 完整回归 | **399 passed、2 warnings（122.67 秒）** | `a4478a6`，按下节正式 pytest 入口执行，启用真实 Chrome，无跳过项；两警告分别为 Starlette/httpx 弃用及 Alembic path_separator。399 项包含既有商城、客服、模型预算和费用守卫测试，未由分批结果拼接 |
| 桌面与移动真实 Chrome | **最终完整运行中通过** | 真实商城 API/数据库、合成政策与模型。每端均完成已保存物流/退款能力说明、合成索引故障及独立查单、未支付方案、用户确认、提交后丢失响应及核验。合成组合 exchange 14 次、商品 exchange 4 次；真实提供方及 WeKnora 请求 0。终态确认说明替换旧未知文案 |
| 当前分支 Playwright 页面模拟套件 | **28 passed（26.2 秒）** | 完整 `e2e/customer-service.spec.ts`；逐项来源、确认 executed/lost/processing 三参数、未知结果与生命周期通过。Chrome + 模拟 API，与真实事务证据分开 |
| 六工具合成模型及受控失败 | **最终完整运行中通过** | #9 初始新增 15 项全部通过，含两种物流退款表述、待支付方案、政策故障、六工具成功与 10 个失败参数；不代表真实六工具提供方兼容性 |
| 审查修复回归 | **新增 20 个参数均包含在最终 399 项通过中** | 超时/持久重放/撤销方案 5、后续商品故障含预算回退 4、组合重试分类/总额 5、独立订单重试 2、交付权限复核 4。公共入口见[审查修复记录](customer-service-composition-review.md#修复与验证状态) |
| 测试账本隔离 | **通过；最终只读查询未结束预留 0 条** | `order_client` 结束自有受控 transport 后，仅清理本次随机测试买家所属会话的预留；保留原费用守卫断言，未清空全表或放宽安全校验。只读目标返回 `shop_test` |
| 独立离线相关性参考 | 40/40 通过 | `python3 -I docs/policy-relevance-offline.py`；无外部调用，未回放临时真实候选文件；不代表商城 API 或生产质量 |
| 部署静态预检 | 通过 | `python3 -I deploy/customer-service-demo/preflight.py`；合成配置，默认 0 服务；未启动/更新容器 |
| 当前持久演示与恢复 | **#9 镜像部署、两端真实 Chrome 及新卷恢复通过** | 用户后续授权后，主演示升级为 `4e43485` 镜像，保留数据库卷；deployment 44、outage 8、recovery 10 次脚本计数检查分别通过，不能与 pytest 项数相加。恢复总耗时 478.269 秒；[准确镜像、权限、故障及复现记录](../deploy/customer-service-demo/ticket-9-acceptance.md) |
| 全后端类型检查 | **未通过：18 项既有诊断，无新增** | 最终 `uv run --project backend ty check backend/src/shop_api`；分布仍为 cancel 7、model_budget 3、model_transport 5、spend_guard 1、reconcile_demo_catalog 2 |
| 构建、变更模块类型及语法/差异检查 | **通过** | `npm run build`、七个变更生产模块 `ty check`、Node 脚本及页面内联 JavaScript 语法、变更 Python AST、`git diff 12f9346...HEAD --check`；94 个本地文档链接/锚点、32 个唯一场景编号与 45 个具名后端测试入口检查通过。不把既有诊断写成全项目类型通过 |
| 两轴代码审查及修复 | **已完成修复并回归** | 固定初审 `12f9346...039c7c4`；Standards 2 项、Spec 3 项，重合后 3 处，另有真实截图发现的终态说明及完整回归发现的测试隔离，共 5 处。统一修复 `f3a9951` 合入 `7fa0370`；测试时钟补齐 `a4478a6`；分轴报告及各项证据见[组合审查](customer-service-composition-review.md) |

历史失败保留：`290d3e7` 首次完整运行 **366 passed、13 errors、2 warnings（111.16 秒）**，不能称通过。13 项均在费用守卫夹具阶段发现一条订单合成故障测试留下的未结束预留，尚未进入用例正文；不确定 exchange 保留 13500 tokens 预留符合产品契约，修复的是测试自有记录的 teardown。只读检查确认该行属于测试买家且 TTL 已到；首次直接维护被自动审批拒绝后，用户另行明确授权一次既有到期扫描，实际结束 1 条过期预留，记录及全额计费保留。费用守卫当时单独重跑 **13 passed（1.72 秒）**，未与首次结果拼成完整通过。

`7fa0370` 的修复定向运行曾为 **50 passed、9 failed（23.55 秒）**。9 项新超时/交付权限测试的时钟替身缺少安全日志探针所需的 `monotonic_ns`，提前触发模型保护，未到达预期模拟阶段。`a4478a6` 仅补齐测试时钟接口，保留安全检查及断言；定向重跑 **9 passed、37 deselected（8.39 秒）**，之后才执行上表独立完整 399 项运行。初始组合 API 的 TDD 和 26 项页面运行属于较早版本的过程证据，不累计为最终覆盖数。

## 本地重复验收入口

先确认测试容器实际目标为 loopback 的独立 `shop_test`、无其他并行数据库测试。只在当前终端设置两个数据库地址，应用导入所用 `SHOP_DATABASE_URL` 必须与 `SHOP_TEST_DATABASE_URL` 相同；密码从受控本地环境取得，不打印或提交：

```sh
export SHOP_TEST_DATABASE_URL='postgresql+psycopg://shop:<测试专用密码>@127.0.0.1:55445/shop_test'
SHOP_DATABASE_URL="$SHOP_TEST_DATABASE_URL" \
  SHOP_ALLOW_TEST_DATABASE_RESET=1 SHOP_RUN_BROWSER_TESTS=1 \
  uv run --project backend pytest backend/tests -q
```

完整后端测试调用真实 Chrome 时，夹具会在 loopback 临时端口启动商城 API 并挂载同源静态页，结束后回收服务。测试运行所需的合成 exchange 与政策由受信构造器/夹具提供，不启用真实外部调用，也无需启动持久演示容器。截图保存在该次 pytest 的 `tmp_path` 下，由夹具通过 `SHOP_BROWSER_TEST_ARTIFACT_DIRECTORY` 传给浏览器脚本；桌面/移动组合截图为 `ticket-9-composite-desktop.png`、`ticket-9-composite-mobile.png`，不使用固定共享 `/tmp` 文件作成功判据。临时截图只辅助核对页面，公共请求断言仍是通过依据；它们不是长期证据归档。

页面模拟测试另在一个终端启动 `npm run dev -- --host 127.0.0.1 --strictPort`，在另一终端运行 `npm run test:e2e -- e2e/customer-service.spec.ts`；完成后停止本次启动的 Vite。Chrome 路径沿用 `playwright.config.ts`。构建使用 `npm run build`。若环境缺少 Chrome、Node 或专用测试库，应记为阻塞，不能跳过后声称完整通过。

自动真实演示由 `test_customer_service_browser.py` 准备专用虚构账号、本人已发货单及每端各一笔待支付单；账号、随机订单号和同源临时端口只传给该次浏览器进程。桌面 `1440×1000` 与移动 `390×844` 分别完成相同交互：

1. 登录专用买家，点击“查询我的订单”，再亲自点击已发货订单详情；不能由列表自动选单。
2. 输入“快递未到且想退款”，核对已保存物流、无实时轨迹/预计送达/退款接口说明，以及未生成取消确认卡。
3. 由测试专用入口令合成政策索引不可用，输入“演示商城多久发货？；查询我的订单”；订单详情仍成功，政策项显示不可用及各自查询时间，随后固定“查询我的订单”仍独立完成。
4. 恢复合成索引，明确选择该端专用待支付订单，再提出物流/退款组合诉求；核对仅提出取消方案且订单仍待支付。
5. 点击“确认取消订单”；测试让真实确认提交后丢失响应，页面只核验执行结果。只有操作证据与独立订单 API 一致，才显示本次取消成功；终态说明替换旧未知/处理中说明，不自动重发取消。
6. 检查确认凭据未进入 DOM/storage、页面没有横向溢出，再保存该端截图。脚本中的其他流程另验匿名读取、跨会话拒绝、核验先到和迟到确认。

这组测试库交互由夹具完整驱动；后续部署的确定性组合、能力不可用处理与新卷恢复由 `e2e/customer-service-deployment.mjs` 另行验证，见[部署实绩](../deploy/customer-service-demo/ticket-9-acceptance.md)。两类证据分开，截图不替代各次请求的状态、正文和绑定断言。

## 工单验收状态与未完成项

| #9 条目 | 当前交付状态 | 放行限制 |
|---|---|---|
| 快递未到且想退款的组合演示 | 合成实现与修复已合入，最终 API、桌面/移动真实 Chrome 及 Mock 页面通过 | 只适用取消方案；无退款、实时轨迹或人工受理能力 |
| 政策故障与独立订单、同权限模型组合 | 确定性及合成协议路径已验证；六工具、授权、隐私、预算与失败部分结果回归通过 | 六工具真实提供方兼容性未验证 |
| 固定黄金/边界/回归/安全输入与证据 | 32 场景均有输入、预期、实际和入口；31 个完整回归通过，R09 后续补齐 #9 镜像恢复 | 各场景按自己的 API/页面/部署证据判断，不以普通取消用例替代客服全链路 |
| 实现/验证/阻塞分开记录 | 本文及各切片、分轴审查记录已更新 | 不填写未测生产解决率、准确率或成本收益 |
| 全部 WeKnora 证据和完整首版 | [W01–W10 能力矩阵已整理](customer-service-weknora-acceptance.md)，合成补偿通过；真实首版阻塞 | 真实政策、适配器/发布清理、权限与真实依赖故障/独立问题集、外部保留未满足；合成部署/恢复通过不替代这些门槛 |

本次已交付可重复的合成组合演示和可审计评测。真实商城首版仍受 [WeKnora 放行阻塞](customer-service-weknora-acceptance.md#真实首版放行阻塞)约束，#9 保持 OPEN；现已补齐合成新版本部署与恢复，真实政策和外部数据门槛仍需按[资料与证据清单](customer-service-real-release-prerequisites.md)完成。
