# 客服 #9：组合实现两轴审查

日期：2026-10-24。固定比较：`git diff 12f9346ce31d009cf01eb32cf9380e4af9665327...039c7c4a7767a3504fe1896e91028e02656e6fc0`。审查覆盖该范围十个提交，与 [#9 原规格](https://github.com/LazyYang-v/docs/issues/9)、[#4 合成范围修订](https://github.com/LazyYang-v/docs/issues/4#issuecomment-6345597736)、[运行契约](customer-service-runtime-contract.md)分别核对。两个独立只读审查均未运行数据库、调用外部提供方或修改源文件。

以下行号指初审版本 `039c7c4`，修复后可能移动。已知真实政策、WeKnora 适配与当前部署/恢复缺口另见[最终评测](customer-service-final-acceptance.md)，不将范围阻塞写成新增越权实施的授权。

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

统一实施修复正在独立工作区进行；完整集成数据库/API/真实 Chrome 回归仍被自动审批拒绝，不能将未执行回归标为通过。修复提交和实际验证结果将在交回后补入本节。
