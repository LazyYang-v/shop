# Issue #1 提供方基础兼容性实测

> 历史记录：保留当轮观察及授权边界；2026-10-23当前范围、已批准参数、证据进展与#1关闭建议以[最终运行契约](customer-service-runtime-contract.md)为准。下文阶段性的OPEN/未授权/待冻结不作为当前结论；实际未验证能力仍受该契约的运行门槛约束。

日期：2026-10-22。用户明确授权继续执行已公布方案：最多3次请求、每请求JSON≤4KiB、输出上限128 tokens、无重试，收费预算上限3元。仅合成数据，未接入商城工具、数据库、买家会话或政策索引；不实施后续票。

## 官方契约与价格

本轮实际获取[价格](https://api-docs.deepseek.com/quick_start/pricing)及[工具调用指南](https://api-docs.deepseek.com/guides/tool_calls)。模型名称deepseek-flash；官方base URL为https://api.deepseek.com，调用POST /chat/completions；非思考模式请求字段为thinking.type=disabled。非流式stream=false，输出约束max_tokens=128；JSON输出使用response_format.type=json_object。

获取时Flash峰时每百万tokens未缓存输入$0.30、输出$1.20，非峰时减半。按每请求4096输入tokens及128输出tokens保守预留，3请求峰时费用上界$0.0041472。未使用Search/Fetch或其他收费工具。

## 实际结果

| 请求 | HTTP / 耗时 | 输入 / 输出tokens | 独立预期与结果 |
|---|---|---|---|
| 非思考JSON | 200 / 969ms | 45 / 6 | 解析JSON并精确匹配合成probe=ok；通过 |
| 工具请求 | 200 / 1004ms | 318 / 54 | 仅一次get_probe_value，参数严格等于key=ALPHA，无额外字段，具备tool_call_id；通过 |
| 工具结果往返 | 200 / 941ms | 141 / 14 | 客户端提供合成只读fixture结果，返回JSON值精确匹配SYNTHETIC_BLUE_7，无追加工具调用；通过 |

三次均无reasoning_content、无length截断；finish_reason依次stop/tool_calls/stop。服务端usage合计输入504、输出74、总578 tokens，报告缓存命中0。按峰时费率估算$0.00024，非峰时$0.00012；此为usage估算，不是账单扣费核对，未换算或宣称准确人民币金额。执行未超出预算预留。

## 证据与限制

本地一次性脚本`/tmp/shop-ticket1-deepseek-verify.py`，脱敏结果`/tmp/shop-ticket1-deepseek-result.json`。脚本只读取本地专用配置，密钥仅进入官方请求Authorization，不记录原始请求/响应、凭据或私人数据；拒绝重定向、非官方base URL及非批准模型，每次发送前限制正文和次数，失败即停。原始响应只在内存解析，证据仅保留结构化判定、用量、耗时和受控状态。

本轮验证常规function工具调用，未启用beta strict模式；additionalProperties=false及精确参数由客户端校验，不能宣称提供方强制所有Schema。未验证六业务工具、多轮复杂编排、恶意输入防护、真实token计量库、共享预算、超时取消及并发控制。usage存在不表示本地预发送计量已经实现。外部提供方日志/备份/保留期限仍待准确来源核实。模型返回不代表任何业务操作执行成功；#1保持OPEN。
