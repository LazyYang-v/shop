# DeepSeek 输入准入与结算

2026-10-23用户修订：精确预发送计量不再是合成流程门槛，离线tokenizer仅作未来精化；本轮真实调用仍未授权。推导见[DESIGN.md](../DESIGN.md#客服模型估算与本地槽位回收2026-10-23更新)，运行优先级见[运行契约](customer-service-runtime-contract.md)。

当前estimated准入对整个JSON执行UTF-8字节数+512≤9830检查，超限拒绝，不静默截断。它是显式规划假设，不声称确定性token上界或经提供方验证。预算独立预留完整12000输入+1500输出；usage允许高于估算值但不超过输入12000/输出1500，结算按实际值。超出上限/无效usage保持保守收费并封锁后续准入，不能消除未知实际收费的所有风险。metering_mode记录到账本，不扩大原安全JSONL日志字段。

90秒本地槽TTL在新预留、结算及维护时原子回收，到期settlement_reason=assumed_max、全额保留原UTC日、迟到响应不退款。TTL恢复本地容量而非证明远端取消；真实远端在途可能超过2，必须在未来真实调用授权中披露。30天清理只删除终态记录。

CompletionTransport真实exchange默认不可调用，合成exchange通过实际ModelTurn.prepare、原子预算、后台worker和usage结算。没有环境变量可伪装verified或放行付费。固定地址、禁止重定向、响应体限制、不自动重试保持。传输器另有两个本地worker许可，在预算预留前无等待准入；占满时立即拒绝，调用方超时取消尚未启动的任务，worker调用exchange前复核剩余期限。Python不能终止已挂起的线程，账本TTL不回收这种worker；两worker挂起时该传输器保持拒绝，需依赖实际返回或隔离进程恢复，不承诺TTL恢复传输吞吐。

2026-10-23 C准备：新增数据库单例持久付费上限（终身200次/2000分，迁移0020），在发送前按受信冻结`PriceCard`预留最坏成本，仅时限内、未超预留上界的有效usage可退款；不明/迟到结果保留全额，超界锁定。它独立于上表的日token预算，二者同时生效。首次真实调用已发生1次（1分，卡片估算），提供方返回usage总量417 tokens后模型循环拒绝响应，按失败即停暂停；修复estimated上界及真实调用ID兼容后待批准重试。价格卡仍为第三方转述的保守峰值价而非官方核验，所以本文件中的token边界仍不等于已验证账单金额。

## 官方材料及已知限制

官方[Token & Token Usage](https://api-docs.deepseek.com/quick_start/token_usage)说明字符比例为近似值，以usage为准，提供[离线V4 tokenizer包](https://cdn.deepseek.com/api-docs/deepseek_v4_tokenizer.zip)，SHA-256为`e7310d1dafe0a86d8a5629fe78a7c763760f651db9b8682718a1781dcd6fe495`。只静态读取清单/文本，未执行下载示例。包示例encode("Hello!")；chat_template未说明顶层tools及response_format计量。配置model_max_length=16384，[模型页](https://api-docs.deepseek.com/quick_start/pricing)当前Flash对应V4.1且上下文更大，不能把配置值冒称API限制。

离线验证不等于实际提供方兼容性；若需要付费核对usage与估算偏差，须单独批准请求数及金额。测试最坏组合2000中文字符+6×1500字节工具结果+历史时明确拒绝，因为前两项已超过9830，不能伪造低于阈值的结论。
