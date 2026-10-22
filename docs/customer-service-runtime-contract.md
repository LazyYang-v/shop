# 客服运行契约：Issue #1 工作记录

核实日期：2026-10-22。状态：**文档契约已集中，部分能力有证据；#1 保持 OPEN，#3/#4 仍阻塞，生产政策自动答复不放行**。本文不表示客服实现完成。

## 当前契约与证据顺序

业务权限以[规格](customer-service-spec.md)、[设计记录](customer-service-design.md)及[ADR](adr/0001-customer-service-authority-boundary.md)为准。具体参数、浏览器 HTTP 路由、错误码及六个模型工具 Schema 采用[集中审核稿第1–8节](customer-service-contract-proposal.md#1-推荐选择与影响)，其中第8节为记录的用户附加条件；相关性资格门采用后续[确定性保护契约](customer-service-relevance-guard.md#保护契约)。设计与参数获附条件批准，不等于实现或测试通过。

下列矩阵汇总当前状态。历史实测记录中的“尚未批准”“未验证”只描述当轮状态；最新进展由本表及所引后续记录说明，不改写原始观察。审批仅引用已有文档中的记录，GitHub [#1](https://github.com/LazyYang-v/docs/issues/1) 当前无评论；本次没有取得新的参数、消费或轮换批准。

## 政策验证最新结论

[离线24项验证](customer-service-policy-offline-evidence.md)通过；后续获准的[5份文档/12题真实检索](customer-service-policy-live-evidence.md)及清理已完成，共32次检索。实际文档ID可映射合成登记，版本资格回放排除了撤回及未来版本；但统一hybrid分数阈值未通过，同一B1在标签正例及库存负例都得约1.0分。不能冻结生产阈值，政策自动答复仍不放行；已按用户指示确定[有限范围确定性相关性保护](customer-service-relevance-guard.md)：全句规则解析实体/主题/条件，未知则澄清；候选ID按登记范围及有效期复核。40项离线及12题已有真实候选回放通过，替代hybrid阈值方案；仅合成覆盖，不是商城实现或独立泛化评测，生产政策自动答复仍不放行。5份文档已删除，未调用收费模型、未轮换令牌。

## 参数登记

| 参数 | 当前契约 | 批准及验证状态 |
|---|---|---|
| 模型 | DeepSeek API / deepseek-flash；不借用其他产品认证 | 已确认；官方文档记录见集中审核稿第1节及下方矩阵；未调用验证 |
| 编排及接口 | Python 确定性分流、受限工具循环，无 LangGraph；HTTP 与六工具采用集中审核稿第5、6、8节 | 附条件批准；已设计未实现，不能继续称为完全未决接口 |
| 输出及推理 | 非流式 JSON；优先关闭额外推理，仅在官方参数与模型兼容性核实后设置 | 行为方向已批准；精确 API 参数及工具调用兼容性缺证据，不猜字段 |
| 模型预算 | 输入12000、输出1500 tokens；会话每日50000、部署每日500000；模型并发2、最多4次请求，单次20秒/整轮45秒 | 附条件批准；可靠 token 计量、共享原子预算及兼容性未验证；金额预算须按当时官方价格另批 |
| 检索 | 显式批准KB，hybrid top5，最多3引用，每片段1000字符；检索并发4，单次5秒；每轮仅1次、不重试 | 附条件批准；总步骤10秒不扩大分类次数预算；真实配置及期限传播未全验收 |
| 相关性与 Rerank | 分数仅排序，确定性全句规则解析实体/主题/条件，再按登记复核身份及有效期；首版不额外模型 Rerank | 后续有限范围方案替代最低分数阈值；40项离线及12题保存候选回放通过，不是生产泛化或质量放行 |
| 页面实例 | 每会话10个，LRU淘汰并原子撤销旧资格；闲置10分钟到期 | 附条件批准；未实现，不再按达到上限直接拒绝新建 |
| 确认/交接 | 确认min(签发+120秒,支付截止)；交接90秒、30秒续期，同页一个在途 | 已确认；未表示产品验证通过 |
| 核验 | 锁等待最多1秒；2/4/8秒后每15秒，加0–500毫秒抖动；5分钟硬截止 | 已确认/附条件批准；抖动范围已在集中审核稿第2节明确 |
| 限流、输入、分页、工具额度 | 集中审核稿第2、8节；各分类不可挪用，重试计入预算 | 附条件批准；共享计数及故障拒绝行为待实现验证，不采用平台默认值替代 |
| 数据与保留 | 聊天闲置30分钟/最长24小时；操作证据及用量账本30天、日志7天；政策正文至少至关联证据到期 | 附条件批准，详见集中审核稿第3节；不承诺外部供应商副本同步删除 |
| 清理 | 30秒条件失效/回收周期，每日清理到期证据；入口即时验期 | 附条件批准；并发、事务及失败恢复未产品验证 |

## #1 验收与证据矩阵

“记录通过”表示已有文档记录的实际观察，本次仅重跑下方离线命令；不代表重新访问部署。官方源码链接全部固定 v0.8.3 commit `3e22822c1d2397be730c458c7539d0eb8c113a24`，入口见[官方证据逐项结论](weknora-v0.8.3-evidence.md#逐项结论)，每行含对应精确文件/行号链接。临时证据路径是原记录的本地指针，非永久或公开附件；本次只读取回放所需的检索证据，不声称其余临时文件仍可用。

| #1 要求/能力 | 状态与准确证据指针 | 限制、补偿及未完成项 |
|---|---|---|
| 部署版本 | 已记录 Docker app/frontend OCI 标签 v0.8.3、上述revision及官方source；[官方记录：身份与版本边界](weknora-v0.8.3-evidence.md#身份与版本边界) | MCP 自报1.0.0不是部署版本，见[实测：实际Schema与来源缺口](weknora-live-verification.md#实际-schema-与来源缺口)；本次不复测镜像。原主页HTTP 200只证明前端可达 |
| MCP传输、协议及工具Schema | 官方固定源码为stateless Streamable HTTP；实测initialize HTTP200、协议2025-03-26，通知202；[实测首表及Schema](weknora-live-verification.md#实际-schema-与来源缺口)，本地原证据`/tmp/shop-weknora-live-probe.json`、`/tmp/shop-weknora-scope-probe.json` | search_knowledge仅query、mode、limit、knowledge_base_ids；不具有政策版本/时间过滤参数；完整浏览器客户端兼容性未验收 |
| 工具白名单/最小权限 | [第二轮](weknora-live-verification.md#第二轮用户收紧端点后复测)：tools/list仅search_knowledge，禁用ask返回-32602；请求均显式限定批准库 | 仅当前只读端点；维护写端点独立，不纳入客服工具。不推断所有工具/端点均隔离 |
| 知识库隔离与令牌撤销 | [第四轮](weknora-live-verification.md#第四轮用户指定真实空白测试库的隔离检查)：用户指定真实非授权空白库一次请求被明确拒绝；原证据`/tmp/shop-weknora-real-scope-evidence.json`。无令牌401见首表 | 当前端点/该库范围拒绝有证据；跨租户、所有工具、旧令牌撤销及在途撤销未验证。专用令牌轮换未授权，仍阻塞 |
| 版本、生效区间及来源元数据 | 平台无原生过滤，knowledge_metadata曾为空；[第三轮表](weknora-live-verification.md#第三轮获准合成文档的更新与清理)。补偿为商城不可变版本登记、KB+文档ID、规范正文、UTC[from,to)；[24项历史离线记录](customer-service-policy-offline-evidence.md#场景结果)、[实际ID映射回放](customer-service-policy-live-evidence.md#实际id映射的离线回放) | 合成ID映射与版本拒绝支持可行性，非商城发布原子性或完整API实现。来源无法映射即拒绝；真实批准政策、条件、正文及维护权限控制未提供/验证 |
| 更新、删除及旧条目残留 | [第六轮](weknora-live-verification.md#第六轮新合成文档更新与删除复测)：首次仍旧内容，间隔4秒下一轮新内容；三模式删除后目标0命中。原证据`/tmp/shop-weknora-retest-evidence.json`。五文档后续清理见[执行及清理](customer-service-policy-live-evidence.md#执行及清理)，原证据`/tmp/shop-policy-live-cleanup-evidence.json` | 4秒不是SLA；仅top-k及观察窗口。Wiki/直接读取/全缓存未验证；失效瞬间原始检索零旧命中仍未满足。商城立即撤回引用加异步清理不等同平台零残留 |
| 混合检索、分数与Rerank | 官方矩阵“混合检索与Rerank”行给出RRF及MCP传nil rerankModel源码；[12题结果](customer-service-policy-live-evidence.md#固定12题结果)记录hybrid top5，无partial_failures；Q02/Q11同B1约1.0分证明[单阈值失败](customer-service-policy-live-evidence.md#最低阈值不通过) | 暂不额外Rerank获附条件接受，非质量通过。确定性资格门替代分数阈值，见[保护与剩余缺口](customer-service-relevance-guard.md#与既有条件的关系及剩余缺口)；真实索引权重、降级/部分失败注入及独立问题集缺证据 |
| 超时、限流及错误形态 | [首轮错误表](weknora-live-verification.md)：无令牌401、缺query HTTP200+isError、未知工具JSON-RPC -32602；官方矩阵“超时”“限流与错误”行含确切源码链接 | 平台默认60次/分钟、Redis失败回退本地、无统一search deadline仅为源码事实；不等于批准商城预算。真实超限、依赖超时、取消传播、共享计数及失败恢复未测；禁止压力探测。断连不推断依赖停止，在途继续占额度 |
| 提供方、编排、接口及参数冻结 | 参数表及[集中审核稿第1–8节](customer-service-contract-proposal.md#1-推荐选择与影响)为记录的附条件批准；DeepSeek官方入口[API文档](https://api-docs.deepseek.com/)原记录为OpenAI格式、Bearer、base URL `https://api.deepseek.com` | 参数不再笼统标未决；模型调用、精确推理参数、token计量和外部保留仍缺证据。未批准人民币预算；不授权付费测试 |
| 安全测试范围及证据脱敏 | [配置模板](customer-service-test-config.example.env)、[五文档执行及清理](customer-service-policy-live-evidence.md#执行及清理)：5次创建/5次删除/32次检索，别名公开、无端点及令牌；[保护验证](customer-service-relevance-guard.md#可复现验证)为离线 | 历史限定写入已完成，不自动续期；配置存在不授权任何网络请求。本次无配置/秘密读取，无网络推理、WeKnora请求或外部写入 |

## 本次安全离线验证（2026-10-22）

按TDD技能适配文档工作：检查边界为已授权的“契约对记录证据的一致性”及现有离线脚本CLI；未新增测试或产品代码。修订前发现的失败条件为：运行记录仍将预算/接口/抖动称未决定，集中审核稿仍要求已被替代的分数阈值，并把已有合成映射回放称全未验证。修订后逐项核对批准状态、证据层级与阻塞项；不将此文档核对冒称自动化测试通过。

读完脚本后确认仅Python标准库、无网络/数据库/凭据依赖，实际执行：

```bash
python3 -I docs/policy-relevance-offline.py
python3 -I docs/policy-relevance-offline.py \
  --evidence /tmp/shop-policy-live-search-evidence.json
```

两条命令均退出0：自包含40/40；第二条亦40/40，另保存候选回放12/12。当前输出分别保存在本地`/tmp/shop-ticket1-offline-current.json`及`/tmp/shop-ticket1-replay-current.json`。生产阈值仍为null，回放没有重新检索。

这是已知合成开发/回归样例；历史39/40后收紧语法的过程见保护记录，不是独立盲测或生产泛化。旧24项映射检查仅引用历史报告，本次未重跑（相应临时脚本未作为可复现产品测试提交）。未运行商城API、数据库、浏览器、并发、模型兼容性或真实故障测试；不声明这些通过。

## 剩余阻塞与放行条件

- 专用令牌旧值撤销/新值限定库访问未验证；轮换需另行明确授权，不能依据现有配置自动执行。
- “失效瞬间平台原始检索零旧命中”仍无保证，需明确该强要求与已批准的商城拒绝引用/异步清理之间的验收取舍；本次不代用户放宽。
- 需真实批准政策、主题/条件、模板和独立问题集，验证登记与来源、条件重叠及交付一致性；已有合成补偿可行性不足以放行生产自动答复。完整产品路径仍归后续票，本次不实现。
- 超时/取消传播、实际限流与错误/降级、共享计数和用量计量尚缺相应边界证据；官方文档事实不能冒充部署实测。
- DeepSeek工具兼容性、精确推理参数、外部保留需核实；付费验证须另批请求及金额预算，当前无收费推理授权。

本次完成 #1 的文档集中及安全离线复验，未满足 #1 全部验收。保持 Issue OPEN，不解除后续依赖，不进行外部 Issue 写入。
