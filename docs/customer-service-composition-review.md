# 客服 #9：组合实现两轴审查

日期：2026-10-24。固定比较：`git diff 12f9346ce31d009cf01eb32cf9380e4af9665327...039c7c4a7767a3504fe1896e91028e02656e6fc0`。审查覆盖该范围十个提交，与 [#9 原规格](https://github.com/LazyYang-v/docs/issues/9)、[#4 合成范围修订](https://github.com/LazyYang-v/docs/issues/4#issuecomment-6345597736)、[运行契约](customer-service-runtime-contract.md)分别核对。两个独立只读审查均未运行数据库、调用外部提供方或修改源文件。

以下行号指初审版本 `039c7c4`，修复后可能移动。后续 `4e43485` 已补齐实际部署及新卷恢复；当前按用户批准的[作品集发布范围](customer-service-portfolio-release.md)收口，真实政策与 WeKnora 产品接入归档为生产化条件，不阻塞作品集。下列两轴发现和修复仍保留原审查版本，不改写为新一轮审查。

## Standards

1. **P2，违反冻结超时规则。** `backend/src/shop_api/customer_service_consultations.py:366` 在工具已有核验事实后仍无条件检查 45 秒期限；后续模型等待耗尽整轮时间时，路由丢弃事实、返回通用 503，并保留 processing 消息，重放成为 425。[冻结规则](customer-service-contract-proposal.md#达到预算和超时的确定行为)要求 `partial/turn_timeout`，并撤销未交付方案的可用凭据。
2. **P2，重试超过分类/总额度。** `backend/src/shop_api/customer_service_composite.py:58` 按门面逻辑调用计数，而 `customer_service_orders.py:219` 对可重试 SQL 故障递增计数后仍继续读取。先列表后详情的第二次调用失败时，可能产生第三次订单尝试，六工具整轮可能达到七次。[冻结工具规则](customer-service-runtime-contract.md#冻结参数)要求重试也占订单两次及总六次额度。

未发现另需整改的 Fowler 代码气味；这些判断不由其他工具已强制的格式/类型检查替代。规范轴共 2 项，最严重影响是超时丢弃已核验事实并留下无法完成的消息。

## Spec

1. **P2，超时丢弃部分结果。** 与规范轴第一项相同；触发为已选本人订单读取成功，后续模型等待耗尽 45 秒。[冻结规格](customer-service-contract-proposal.md#达到预算和超时的确定行为)明确“有核验结果返回 partial + turn_timeout；无结果 503”，不能把两类状态合并为依赖失败。
2. **P2，确定性组合中后续故障丢弃独立事实。** `customer_service_consultations.py:359` 调用 `run_deterministic` 无部分结果保护；`customer_service_composite.py:249` 在已选订单读取成功后遇到商品 fixture 不匹配或依赖错误，异常直接变成 503，没有订单事实。[部分结果规则](customer-service-contract-proposal.md#5-浏览器http契约建议)要求已有核验数据时显示已完成项、来源及时间。模型预算不足时的确定性回退也需同样保护。
3. **P2，分类重试额度。** 与规范轴第二项相同；冻结规格要求“实际尝试含只读重试均消耗所属额度”“订单查询（列表+详情）≤2”，新组合的列表/详情往返不能绕过限制。

规格轴共 3 项，最严重影响是整轮超时后无法交付和重放已核验结果。没有以尚未执行的证据行推导通过，也没有要求开启真实政策或真实 WeKnora。

## 修复与验证状态

初审为规范 2 项、规格 3 项，重合后共 3 处。主线程随后读取实际桌面/移动截图，发现第 4 处页面状态问题：`public/customer-service.html:225` 的 `expireConfirmationCard` 在已有 `.invalid-note` 时直接返回；响应丢失后先写入“响应未能确认”，终态核验成功时无法替换为“本次取消已由商城订单与操作证据确认”。页面会同时显示成功和旧未知说明。该项与前三处交由同一实施工作区修复，并补模拟页面及真实浏览器终态断言。

统一修复提交 `f3a9951` 已合入集成分支 `7fa0370`，随后 `a4478a6` 补齐新增超时测试的时钟接口。Standards 与 Spec 的初审报告按原轴保留；以下逐项记录整改及实际验证，不把初审改写为未发现问题。

| 修复项 | 最终行为 | 验证入口及结果 |
|---|---|---|
| 规范 1 / 规格 1：整轮超时 | 停止模型/工具调度，以独立有界 3 秒复核当前权限及页面选择；有核验事实持久交付 `partial/turn_timeout`、可跨应用重放，无事实 503；失败移除确认卡并撤销 pending 凭据 | `test_composite_deadline_persists_verified_partial_and_revokes_proposals` 5 参数与 `test_composite_timeout_revalidates_current_access_before_partial_delivery` 4 参数通过；覆盖签发途中超时及交付阶段到期，权限变化不泄露已有订单事实 |
| 规格 2：后续依赖故障 | 确定性组合及预算不足的只读回退均保留先前核验订单；后续商品 fixture/依赖故障返回持久 partial、来源及时间，不交付可用确认卡 | `test_composite_later_product_failure_preserves_selected_order` 4 参数通过，原确认凭据失效、订单和库存不变 |
| 规范 2 / 规格 3：重试额度 | 商品/订单重试先扣共享分类和总额度；订单本地读取也最多两次，子查询重试不能形成第三次；MCP 只映射受控 `tool_budget_exhausted` | `test_composite_read_retries_share_classified_and_total_budget` 5 参数、`test_standalone_order_read_retries_stop_at_two_attempts` 2 参数通过；未调度超限后续工具 |
| 实测页面终态说明 | 已有 `.invalid-note` 更新为当前终态说明，核验成功后不残留未知/处理中说明 | Mock Chrome executed/lost/processing 三参数及真实桌面/移动提交后响应丢失流程通过，取消没有自动重放 |
| 完整回归暴露的测试隔离 | 先结束自有受控 transport，再仅清理本次随机测试买家所属会话的模型预留；不修改产品对不确定 exchange 保留全额预留的契约，不清空全部账本 | 最终完整 399 项包含费用守卫全部通过；运行后只读查询 `shop_test` 的未结束预留为 0，原预算夹具断言保留 |

上表前 3 处新增后端回归共 20 个参数，全部包含在 `a4478a6` 的独立完整运行：**399 passed、2 warnings，122.67 秒**，包括真实 PostgreSQL API 与桌面/移动真实 Chrome。页面模拟套件另行运行 **28 passed，26.2 秒**；二者不相加计算端到端覆盖。七个变更生产模块类型及构建通过，全后端仍有 18 项既有类型诊断，无新增。真实政策、六工具真实提供方兼容性和 WeKnora 外部故障不由这些本地证据放行。

历史失败保留：`290d3e7` 首次完整运行 **366 passed、13 errors（111.16 秒）**。13 项费用守卫均未进入正文，因为合成订单故障测试留下 1 条未结束模型预留。只读检查确认属于测试买家且 TTL 已到；首次直接维护被自动审批拒绝后，用户另行明确授权一次既有扫描。实际结束 1 条过期预留，记录及全额计费保留；当时费用守卫单独重跑 **13 passed（1.72 秒）**，没有拼成完整通过。

修复集成后的定向运行曾为 **50 passed、9 failed（23.55 秒）**：新增测试替换 `time` 时只提供 `monotonic`，遗漏安全日志探针使用的 `monotonic_ns`，提前触发保护而未进入预期超时阶段。`a4478a6` 补齐两处测试时钟接口，未削弱生产检查或测试断言；9 项定向重跑通过（8.39 秒），随后完整 399 项通过。
