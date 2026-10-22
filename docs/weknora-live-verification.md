# WeKnora 专用端点实测记录

日期：2026-10-22。Issue #1；状态：部分验证，未放行。使用用户本地填写的专用测试配置，仅作显式指定知识库的低量检索，没有调用 ask、没有列举或读取其他知识库、没有新增修改删除条目、没有调用 DeepSeek。配置值和知识正文均不进入本报告。

实际命令：`python3 -I /tmp/shop-probe-weknora.py`。临时探针仅在内存加载配置，证据只存工具 Schema 和响应结构，不存令牌、端点或知识库标识。此脚本是核实辅助，不是客服实现。

| 检查 | 实际结果 | 能证明与限制 |
|---|---|---|
| initialize | HTTP 200；协商协议 2025-03-26 | MCP 初始化可用，不等于全部功能通过 |
| initialized 通知 | HTTP 202 | 通知被接受 |
| tools/list | HTTP 200；9 个工具 | 白名单不是期望的仅 search_knowledge |
| 指定知识库 hybrid 检索，limit=1 | HTTP 200；返回 structuredContent、无 isError | 查询被处理；不据此断言政策命中质量或版本元数据完备 |
| search_knowledge 缺 query | HTTP 200，result.isError=true | 业务工具失败不能只看 HTTP 状态 |
| 不存在的工具 | HTTP 200，JSON-RPC error.code=-32602 | 未知工具拒绝；不是已知被禁用工具白名单负向测试 |
| 无令牌 initialize | HTTP 401 | 缺凭据拒绝；不等于跨知识库隔离/撤销已验证 |

## 第一轮工具范围阻塞（第二轮已收紧）

实际工具名：ask、grep_chunks、list_documents、list_knowledge_bases、read_document、search_knowledge、wiki_index、wiki_read_page、wiki_search。

仅调用 search_knowledge。ask 按固定版本源码会创建会话和运行 Agent，不能作为只读检索默认开放。需要用户在专用端点把工具白名单收紧为 search_knowledge，再复测实际 tools/list。知识库请求虽显式限制到获准 ID，端点本身的知识库权限仍未证实，应显式设置专用知识库，不使用全部知识库。

## 实际 Schema 与来源缺口

search_knowledge 输入为 query（必需）、mode（hybrid/semantic/keyword）、limit（描述默认10最大30）、knowledge_base_ids（可选）。没有政策版本或生效区间参数。此为实际 tools/list 结果，支持此前固定提交研究结论。

检索 structuredContent 顶层字段为 count、display_type、kb_counts、knowledge_base_ids、mode、queries、query、requested_mode、results。正文与条目未落盘，本轮只验证响应结构；尚未核实实际条目的来源/版本强制映射、命中数、政策文本、更新删除传播或 Rerank 效果。

初始化 serverInfo.version 返回 1.0.0，这是 MCP 服务自报版本；不可用它替代 Docker 镜像 v0.8.3 部署版本。

## 第二轮：用户收紧端点后复测

- 重新 initialize、通知及 tools/list 成功，实际列表仅 search_knowledge。
- 对已禁用 ask 发送空参数调用，返回 JSON-RPC -32602；未执行 ask，也未创建会话或运行 Agent。与工具列表合并证明该工具已不可调用，不把缺参错误单独当作授权证据。
- 使用随机生成、不对应任何已知真实知识库的 ID 作负向检索，HTTP 200、isError=true，并带明确范围拒绝。只验证此输入被拒，不等于两个实际知识库/租户间隔离已验证；未查询其他真实库。
- 显式指定批准库，hybrid、limit=1 查询：HTTP 200、count=1、results长度1，实际mode及requested_mode均为hybrid，未见partial_failures字段。结果有chunk_id、chunk_index、knowledge_id、knowledge_base_id、knowledge_metadata、knowledge_title等字段。未输出正文、字段值或标识。
- 无令牌仍401，缺query仍为工具isError。没有修改任何文档、令牌、端点设置或调用DeepSeek。
- 临时结构证据为 /tmp/shop-weknora-live-probe.json 与 /tmp/shop-weknora-scope-probe.json；第二轮覆盖前一个临时文件，第一轮结果保留在本报告。

## 第三轮：获准合成文档的更新与清理

用户明确授权仅更新、删除本次合成文档 d0ef2627-9162-4da4-a1f7-8f1e1b9d2648，不处理其他文档。写入端点列出 add_document、update_document、delete_document、search_knowledge；检索实际仍走原只读端点，未扩大客服端点权限。

首次新增请求成功，但探针误将返回结构理解为顶层 knowledge_id/id，未提取嵌套 document，因而停止；未重试新增。之后通过唯一标记与测试标题匹配恢复唯一文档 ID。执行命令为 `python3 -I /tmp/shop-weknora-fixture-resume.py`，使用字面固定的授权文档 ID，更新前再确认标记与标题。

| 检查 | 实际结果 | 结论 |
|---|---|---|
| 新增后可检索 | 指定文档有2条分块命中，正文含policy_version: v1 | 创建并进入检索已验证；2条命中不是2份文档 |
| 来源元数据 | knowledge_metadata无键，顶层无policy_version | 正文版本不是强制政策元数据；登记映射仍需补偿 |
| update_document | 接受，structuredContent字段为document、note | 接受更新不等于新索引已生效 |
| 更新后hybrid观察 | 约32.99秒内多次低量查询，未满足全部分块为v2且无旧标记 | 更新检索验收未通过；未定位是异步处理、分块表示还是失败，不扩大为更新永久失败结论 |
| delete_document | 接受，返回deleted、knowledge_id、title | 仅删除明确授权的本次文档 |
| 删除后hybrid/keyword/semantic | 按该文档ID计数均为0，keyword/semantic实际模式分别对应请求 | 三种检索路径本次观察无该文档命中；不证明Wiki、直接读取或所有缓存均无残留 |

清理状态：指定合成文档已删除，检索无命中；本地待清理指针已移除。证据为 /tmp/shop-weknora-fixture-resume-evidence.json，仅保存计数、字段名和观察结果，不含知识正文、令牌或端点标识。未改其他文档、未撤销令牌、未调用DeepSeek。

## 第四轮：用户指定真实空白测试库的隔离检查

用户提供另一个空白测试知识库 ID，用于前述不在端点授权范围内的只读负向测试。仅发起一次 search_knowledge，显式指定该库，limit=1；未写入、未列举文档、未读取其他库。结果 HTTP 200、isError=true、明确范围拒绝、返回条目数0，本次真实库范围拒绝通过。ID 仅存本地忽略配置，不在此报告重复。

证据：/tmp/shop-weknora-real-scope-evidence.json。结论限于当前检索端点拒绝此库；不扩大为跨租户、所有工具或写入端点隔离均已验证。运行参数、模型预算未因用户提供库ID而获批。

## 第五轮：更新检查未通过的只读排查

仅检查已删除合成文档对应的本地应用日志，并核对固定部署提交源码；没有新增或修改文档、没有轮换令牌、没有调用 DeepSeek。日志原文不落盘，只记录相关时间、事件及版本标记布尔判断。

- 16:06:07.250：更新入队。16:06:07.431：异步任务开始清理；随后日志记录删除2条旧索引。
- 16:06:07.448：生成1个正文分块。该文档的正文预览中确有原样 `policy_version: v2`，未见旧测试暗号；预览并非完整正文，不能据此断言全文不存在旧内容。
- 16:06:07.702：成功保存1条新索引；16:06:07.708：分块处理成功。由此确认这次任务已处理更新正文并写入索引，不能继续把“可能一直排队未处理”当作同等解释。
- 16:06:10.097：日志记录成功生成并索引摘要分块。固定版本源码也明确将摘要作为独立可检索分块，内容由摘要生成结果构造，并不保证逐字保留正文的政策字段。

探针第33行使用 `all('policy_version: v2' in content and old_marker not in content for each_hit)`。它要求每一个检索命中（包括可能的摘要）都保留原样版本字段；这不是有效的通用更新验收条件。摘要分块是此次检查失败的合理解释，但当时只保存命中数与汇总布尔值，没有逐条内容或分块类型证据，无法确定是哪一个返回分块导致失败，也不能据日志宣称检索端已全部返回v2。

修正结论：**更新正文处理与新索引写入已由实际日志证实；检索新版本完整可见性仍未验收，旧探针的失败不能证明检索仍为旧内容。** 后续受控复测应分别验证正文新标记可检索、旧标记检索不再命中目标文档，并区分正文与派生摘要；不能强求每个分块含全部版本字段。权威版本及有效期仍由商城登记映射判断，不能从摘要推断。本轮没有重建已删除条目；新的写入复测仍需明确范围授权。

固定提交来源：

- [异步任务载荷、清理标志及重试/超时配置](https://github.com/Tencent/WeKnora/blob/3e22822c1d2397be730c458c7539d0eb8c113a24/internal/application/service/knowledge_create.go#L1126-L1152)：载荷包含更新正文及 NeedCleanup；任务最多重试3次，单任务超时30分钟。这是队列配置，不是商城可接受的检索等待承诺。
- [摘要分块构造与索引](https://github.com/Tencent/WeKnora/blob/3e22822c1d2397be730c458c7539d0eb8c113a24/internal/application/service/knowledge_process.go#L1666-L1749)：独立 summary 分块，内容来自生成摘要。

## 第六轮：新合成文档更新与删除复测

用户明确授权在原批准库创建一份新合成文档，仅更新、删除该条目；不扩大只读端点、不轮换令牌、不调用DeepSeek。创建返回嵌套document.id；随后只读检索联合核实精确ID、唯一标题及标记，再将该ID固定写入执行脚本。自动审批曾拒绝组合脚本，补齐可见关联证据后执行成功。没有重复创建或重发写请求。

执行：`python3 -I /tmp/shop-weknora-retest-create.py`、`python3 -I /tmp/shop-weknora-retest-identify.py`、`python3 -I /tmp/shop-weknora-retest-execute.py`。本次共13次检索（关联核实1次，执行脚本12次），低于预告24次上限。创建、更新、删除各一次。

| 检查 | 观察 | 结论 |
|---|---|---|
| 创建及归属核对 | parse_status=pending；之后两条命中，唯一标题及旧标记匹配 | 本次新条目可检索，更新清理目标已核实 |
| 更新接受 | parse_status=pending | 接受不等于立即传播 |
| 更新首次keyword检查 | new及old查询均返回含旧标记的片段，不含新标记 | 实际观察到短暂旧内容可见窗口 |
| 间隔4秒后的下一轮keyword检查 | 两条命中均含新标记、不含旧标记；其中仅一条含原样policy_version: v2 | 新内容已可检索；原all版本字段条件在本次数据上会误判。4秒为轮询间隔，不是精确传播耗时或SLA |
| hybrid与semantic新旧标记检查 | 两种模式各查询new和old；目标片段均含新标记、不含旧标记 | 当前返回片段无旧标记；old查询仍能匹配新片段，不能把命中文档本身当作旧内容残留 |
| 模式与错误 | keyword/hybrid/semantic实际模式与请求一致，未报告partial_failures | 本次没有观察到模式降级或部分失败 |
| 删除及清理 | deleted=true；三模式公共标记检索目标命中均0，本地清理指针已移除 | 本次合成文档已删除，三条检索路径观察清理通过 |

分块类型字段未返回，均记录unknown；不依据序号断言哪条是正文或摘要。结果限于本次查询、top10和观察窗口，不证明索引全量、Wiki、直接读取或全部缓存无残留。两条命中的版本字段差异支持修正后的验收方法，但不能倒推上一份已删除文档的逐条内容。

证据：/tmp/shop-weknora-retest-evidence.json，仅含模式、计数、分块序号及标记布尔值，不含正文或凭据。测试文档已清理，没有待清理指针。本轮更新检索和三模式删除观察通过；政策权威版本映射仍未验收。

## 尚需完成

1. 工具列表、禁用工具及用户指定真实空白库的范围拒绝已通过；令牌撤销仍未实测，不扩大为跨租户或所有工具隔离已验证。
2. 来源标识、版本与有效期的权威登记映射，以及政策冲突和旧版本处理仍需验证。
3. 新合成条目更新检索与三模式删除观察已通过（第六轮），无需继续写入复测；测试令牌撤销仍需明确范围，未批准不执行。
4. 官方已知缺少政策时间过滤、此 MCP 路径未启用模型 Rerank，需要批准且验证补偿或明确不纳入首版 Rerank 要求。
5. 冻结尚未批准的运行参数与确切接口契约。保持 #1 OPEN，#3 仍阻塞。
