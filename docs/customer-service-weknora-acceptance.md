# 客服 #9：WeKnora 能力、补偿与放行边界

更新：2026-10-24。关联：[工单 #9](https://github.com/LazyYang-v/docs/issues/9)、[运行契约](customer-service-runtime-contract.md)、[#4 合成政策范围修订](https://github.com/LazyYang-v/docs/issues/4#issuecomment-6345597736)。

**真实 WeKnora 与真实商城政策入口保持关闭。** 当前代码使用合成权威登记和进程内合成索引。历史真实端点观察、固定版本源码、离线参考模型以及商城合成实现是四类不同证据；任一类通过都不自动替代其他类。本轮不读取端点秘密、不调用 WeKnora、不新增或删除共享知识库内容。

## 平台能力证据

历史部署核实时间为 2026-10-22；官方源码固定在 v0.8.3、提交 `3e22822c1d2397be730c458c7539d0eb8c113a24`。下表沿用仓库内脱敏记录，不声称 2026-10-24 重新请求端点或当前部署仍保持相同配置。MCP 自报版本 `1.0.0` 不能取代部署镜像版本。

| 编号 | 能力 | 已有事实与证据 | 补偿、验证及尚未放行的范围 |
|---|---|---|---|
| W01 | 部署版本、传输、初始化与 Schema | [官方版本与路由](weknora-v0.8.3-evidence.md#身份与版本边界)；[真实初始化与 Schema](weknora-live-verification.md#实际-schema-与来源缺口)：stateless Streamable HTTP，协议 2025-03-26，initialize 200、通知 202。检索仅接受 query、mode、limit、knowledge_base_ids | 当前商城没有真实 WeKnora 适配器；新端点须重新验证 Schema、协议和最小权限。商城内部 ASGI MCP 测试不是外部 WeKnora 证据 |
| W02 | 政策版本及生效区间 | 固定版本源码与实际 Schema 均无政策版本/时间过滤；[官方表](weknora-v0.8.3-evidence.md#逐项结论) | 商城按 KB+文档 ID 回映权威登记，校验状态、版本、UTC `[from,to)`；[24 项参考检查](customer-service-policy-offline-evidence.md#场景结果)、[真实 ID 离线回放](customer-service-policy-live-evidence.md#实际id映射的离线回放)及 [#4 合成实现](customer-service-policy-implementation.md#实现边界)分别证明可行性与合成实现。不能据此声称真实来源治理或维护发布已完成 |
| W03 | 来源与元数据 | 真实命中包含 KB、knowledge、chunk 等标识；历史合成文档 metadata 为空、无顶层 policy_version；[来源缺口](weknora-live-verification.md#实际-schema-与来源缺口)、[更新观察](weknora-live-verification.md#第三轮获准合成文档的更新与清理) | 来源、正文哈希、版本、生效依据由商城登记产生；未知映射拒绝引用，索引摘要及自称版本不授予回答资格。真实批准政策与来源尚未提供 |
| W04 | 更新、删除及旧条目残留 | [第六轮真实复测](weknora-live-verification.md#第六轮新合成文档更新与删除复测)：更新接受后曾返回旧片段，间隔 4 秒的下一轮返回新标记；删除后三模式目标 0 命中。后续 [5 份合成文档](customer-service-policy-live-evidence.md#执行及清理)创建/删除各 5 次、32 次检索，清理观察全部目标 0 命中 | 商城撤回立即阻断引用，索引异步删除并三模式检查；参考模型及合成实现拒绝旧/未来/删除残留。4 秒是观察间隔，不是传播 SLA；top-k 零命中不证明全部索引、Wiki、直接读取、缓存或备份清空。真实维护清理流程未接入 |
| W05 | 工具白名单 | [收紧后真实复测](weknora-live-verification.md#第二轮用户收紧端点后复测)：只列 search_knowledge，禁用 ask 返回 -32602；首次端点曾暴露额外工具，未放行该配置 | 客服不开放 ask、Wiki、写入工具、任意 URL 或通用透传；新增真实适配器须独立强制白名单，不能只信模型工具列表。原端点历史结果不证明新端点配置 |
| W06 | 认证、KB 隔离、令牌撤销 | [真实空白库负向检查](weknora-live-verification.md#第四轮用户指定真实空白测试库的隔离检查)被拒、0 条目；无令牌 401。最终轮换 [持久摘要](customer-service-runtime-contract.md#持久脱敏令牌轮换证据)：旧值 initialize 401、新值 200、批准库检索成功 | 仅证明已测端点、知识库与新请求；跨租户、所有工具、写入端点、禁用/删除及在途撤销未验证。不得由无 token 401 推断全部隔离成立 |
| W07 | 超时及取消传播 | 固定源码没有 search 统一总 deadline；[代理观察](customer-service-retention-timeout-evidence.md#mcp代理期限与重试)为 connect 30 秒、读写间隔 3600 秒，配置可切换上游 | 冻结检索单次 5 秒/步骤 10 秒、并发 4、政策每轮 1 次且不重试，必须由未来适配器执行。商城合成故障或内部 MCP deadline 测试不证明远端终止；实际慢响应、断连传播及未结束依赖占槽仍待验 |
| W08 | 限流 | [固定源码](weknora-v0.8.3-evidence.md#逐项结论)默认端点 60 次/分钟，Redis 失效回退本地 map；非已批准商城额度 | 真实有效配置、跨进程额度、Redis 故障与超限未实测；未通过压测试探。商城自己的共享限流测试不能作为 WeKnora 限流证据 |
| W09 | 不可用、鉴权和参数错误 | 真实缺令牌为 HTTP 401；缺 query 为 HTTP 200 + isError；未知/禁用工具为 JSON-RPC -32602；KB 越范围为工具错误；[实际记录](weknora-live-verification.md#第二轮用户收紧端点后复测) | HTTP 200 不等于工具成功；异常不能转换成 policy_no_match。真实不可用、partial_failures、模式降级、连接中断与故障恢复未注入；未来适配器必须拒绝未知错误形态 |
| W10 | hybrid、相关性及 Rerank | 固定源码为加权 RRF，MCP 构造传 nil rerank；实际三模式按请求返回，本次未见部分失败。[12 题实测](customer-service-policy-live-evidence.md#固定12题结果)显示无关问题也可得高分，单一分数阈值失败 | [确定性主题资格门](customer-service-relevance-guard.md#保护契约)有 40 项离线检查及 12 题保存候选回放；分数只排序，不能授予引用资格。有限合成开发/回归样例不代表真实政策召回率，也不构成独立生产问题集或“无需 Rerank 即质量通过” |

## 商城补偿的可执行验证

当前合成补偿代码为 `backend/src/shop_api/customer_service_policy.py`，公共接口验收位于 `backend/tests/test_customer_service_policy.py`，浏览器经 `/api/customer-service/messages` 观察结果。功能候选 `941fe4e` 与最终受测 `a4478a6` 产品代码相同，完整后端 399 项通过，包含合成政策、组合故障和桌面/移动真实 Chrome；页面模拟 28 项另列。该候选验收新增真实模型与 WeKnora 请求为 0，六工具模型测试采用合成 exchange，`4e43485` 部署采用确定性组合。#3 历史 `722ed62` 的 6 次真实模型请求（2 次诊断失败、4 次成功）独立见[兼容性归档](customer-service-issue-3-acceptance.md#c-真实调用与重试验收2026-10-23)，不等于当前六工具或 WeKnora 接入实测。`docs/policy-relevance-offline.py` 仅是独立参考模型；其结果不能替代商城 API 或真实平台证据。

| 补偿 | 固定场景/预期 | 实现与验证状态 |
|---|---|---|
| 登记权威与来源 | 当前版本返回登记正文、来源、版本及区间；索引指令不改写事实；真实 URL、未标注规则拒绝加载 | #4 合成范围已实现且历史通过；#9 当前版本的运行结果在[最终验收](customer-service-final-acceptance.md)逐项记录 |
| 有效期与撤回 | 旧、未来、撤回、删除残留不引用；交付前撤回使本轮不可用 | 同上；并非原始索引零旧命中保证 |
| 冲突与不可用 | 冲突停止政策结论；有活动登记却无检索结果为 unavailable；无足够政策依据为 no_match | 同上；登记冲突通过损坏登记故障注入验证，正常发布拒绝冲突 |
| 相关性 | 完整主题/条件才匹配，未知条件澄清；分数再高也不能回答另一主题 | 参考资格门及合成实现覆盖；真实政策的主题/条件审核未完成 |
| 独立业务能力 | 政策不可用时固定本人订单查询仍可完成，身份及明确选择要求不变 | #9 当前组合/回归结果记录在最终验收；不依赖真实外部检索 |

## 真实首版放行阻塞

**本节已归档为生产化前置条件，不阻塞作品集或 #9。** 标题保留供历史链接使用。2026-10-24 项目负责人已批准[作品集发布范围与 13 项门槛](customer-service-portfolio-release.md)；下列未知项不改写为已验证，也不在当前交付中要求补齐。

1. **政策及来源缺失。** 需要商城批准的真实规范正文、来源、版本、生效条件及维护责任。合成规则不得填补此项。
2. **真实检索适配与发布清理未实现。** 新端点最小权限、批准 KB 与登记映射、不可变版本发布、立即撤回和异步清理验证均须完成；历史探针不等于产品调用链。
3. **真实依赖故障与质量未验证。** deadline、并发、限流失效、partial_failures、取消传播和独立政策问题集仍缺实际证据；不从成功样例推导普遍保证。
4. **外部保留契约未知。** [外部保留核实](customer-service-retention-timeout-evidence.md)、[提供方政策复核](customer-service-deepseek-policy-review.md)没有证明 API 零保留、训练退出适用性或日志/备份/删除期限。受控虚构数据演示不解除真实数据门槛。
5. **真实候选部署仍须独立验证。** 合成 #9 的[准确镜像部署与新卷恢复](../deploy/customer-service-demo/ticket-9-acceptance.md)已在后续授权范围完成，两端浏览器及 478.269 秒恢复通过。此证据仅覆盖合成政策、虚构数据和默认确定性路径；未来真实政策/适配/提供方候选必须重新完成自己的部署、故障及恢复，不能继承合成结果。

[生产化前置条件（归档）](customer-service-real-release-prerequisites.md)保留上述真实条件与未知字段；用户已决定当前只交付作品集，正式商城政策、真实买家数据处理和账号级契约不属于当前验收。#9 依据用户批准的[13 项作品集门槛](customer-service-portfolio-release.md)收口；不再重复将本节归档项报告为当前阻塞。归档不表示真实条件满足，不宣称真实商城首版验收通过。检索零命中不证明缓存或备份已删除，回复时限不等于删除时限。
