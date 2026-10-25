# 电商客服 Agent：20 份公开资料核实与实施建议

研究日期：2026-10-25。范围：入口路由，售前推荐、对比、尺码与活动，订单物流，售后，人工交接，知识库、记忆、审计、指标及多平台。本文只做资料研究与建议，不修改代码、不建立 issue、不发送外部消息、不运行上游项目或真实付费模型。

本文延续 [已有上游研究](customer-service-ecom-service-agent-research.md)，不重复其逐模块架构介绍。**主体共 20 份独立资料单元，编号 1–20，均取得可读正文或固定版本源码并核读所述部分；小红书用户原创笔记核实数为 0。** 小红书检索、官方课程和页面访问限制单列在文末，不用摘要或页面外壳充数。同一仓库的 README 与辅助核查文件按一个资料单元计数；独立主题的官方文档页面分别计数。

外部资料支持架构、接口和评测设计，不构成本商城政策、退款时限、尺码保证或平台接入授权。任何商城承诺仍须来自商城确认的有效知识条目或受控业务接口。本文不修改 [客服权限 ADR](adr/0001-customer-service-authority-boundary.md) 和 [业务术语](../GLOSSARY.md)。

## 结论与本地基线

下一步最有价值的是让已有能力形成可验证的任务闭环，而非增加 Agent 名称：用户问题和当前待办连贯；商品建议能指回具体商品及有效资料；申请进度与业务执行分别呈现；人工接手有明确责任人；旧知识失效后不再被使用；每个渠道有独立授权与验收证据。路由和工具权限继续由服务端约束。[2][3][9][11][13][14][15][20]

研究时工作区存在并行、尚未提交的实现变更。以下为阅读当时的源码观察，不是本次运行验收；实施前应以最新工作区重新核对。尤其不能把已有工单、知识版本、偏好、尺码续问和服务进度查询重新列为待从零建设。

| 范围 | 本次核读到的已有能力 | 真正还需要补齐或验证的事项 |
|---|---|---|
| 入口与角色 | 六职责定义、确定性路由、版本化提示与工具白名单；支持否定、纠正、待办上下文和低置信升级。见 [角色与路由](../backend/src/shop_api/customer_service_agents.py)。 | `confidence` 中有规则赋值，不能解释为已校准正确率；需要中文真实表达、混合意图和多轮场景的独立评测。 |
| 售前 | 在售目录推荐、知识属性对比、有效尺码表；当前源码支持分轮收集显式单位尺寸、斤到公斤转换及推荐条件续接。见 [知识与建议](../backend/src/shop_api/customer_service_knowledge.py)、[编排](../backend/src/shop_api/customer_service_orchestration.py)。 | 经运营确认的商品属性覆盖、同类属性单位统一、版型与尺码制度、推荐条件修正、缺资料时的澄清质量。单规格商品不能被描述成已有完整多规格库存。 |
| 订单与服务进度 | 复用买家会话，订单必须明确选择；保存的物流信息与承运商实时轨迹区分；新增只读服务进度工具，区分工单状态和执行证据。见 [服务进度](../backend/src/shop_api/customer_service_progress.py)。 | 真实承运商事件、业务执行 Adapter、过期数据提示、外部结果核验与对账。退款、发票和补发仍未接真实执行系统。 |
| 售后与人工 | 服务申请、幂等、人工审核、工单接手/回复/审结、授权后共享必要历史；地址变更存在受控执行路径。见 [工单模型](../backend/src/shop_api/customer_service_support.py)、[工作台接口](../backend/src/shop_api/customer_service_support_api.py)。 | 工单解决与退款到账等业务完成持续分离；跨系统接手确认、等待时间、重开和外部执行异常恢复。 |
| 知识与记忆 | 已有发布状态、版本、生效区间、冲突不引用、商品下架过滤；本次咨询上下文、工单 30 天和主动保存偏好 90 天。 | 运营资料质量、来源审核、撤回后的各消费路径一致性；接真实检索后索引/缓存/引用失效链路；偏好修改、删除与跨账号隔离持续验收。 |
| 指标与渠道 | 指标已显示分子、分母及口径；五渠道登记只有 `storefront` 返回已接入，其他返回未配置。 | 反馈覆盖率、任务成功和协议成功分离、人工等待/接手指标、版本化评测；真实平台授权、消息和订单权限分别验收。 |

## 来源 1–20：实际访问范围、可支持结论与项目建议

以下“取得正文”表示 HTTP 返回中有可读内容或 GitHub 返回文件内容，不等于运行过系统、验证过营销数据，亦不表示阅读了链接中的所有附属页面。没有可靠元数据的页面不猜测作者或发布日期；统一以本次研究日期作为访问日期。

### 1. Ecom-Service-Agent: 从0到1实战企业级电商客服Agent系统

- **标题与 URL**：[固定版本 README](https://github.com/HuaiNan54321/ecom-service-agent/blob/b0f55585ad7ed827fd74c3d0f228914adc72bbc1/README.md)。来源：作者 `HuaiNan54321` 的公开仓库；并非商城政策来源。
- **实际访问范围**：通过 `gh api` 重新确认 `main` 为 `b0f55585ad7ed827fd74c3d0f228914adc72bbc1`，提交时间 2026-07-16；取得 README、路由器、编排器、退款工具、评测指标、10 条用例及 LICENSE 正文。未运行项目或付费评测。
- **可支持的具体结论**：README 把 Guardrails、人机协作和 Observability 列为生产篇规划；`Router.route` 从三个角色中选择，无法识别时默认售后，而非表达不确定。退款工具读取 Mock 订单后返回成功话术，没有真实退款事务。评测的 `tool_accuracy` 实际为期望工具的命中比例，未惩罚额外工具；关键字覆盖不能证明业务完成。
- **对本项目的建议**：保留“分流—工具—结果—评测”的教学结构，采用澄清/升级处理未知输入；评测同时检查禁止动作、参数、最终业务状态及回答依据，避免只看期望工具有没有出现。LICENSE 是专有许可，本研究只观察设计，不复制实现。细节沿用已有研究。
- **辅助核查**：[路由源码](https://github.com/HuaiNan54321/ecom-service-agent/blob/b0f55585ad7ed827fd74c3d0f228914adc72bbc1/app/multi_agent/router.py)、[退款源码](https://github.com/HuaiNan54321/ecom-service-agent/blob/b0f55585ad7ed827fd74c3d0f228914adc72bbc1/app/agent/tools/refund.py)、[评测指标](https://github.com/HuaiNan54321/ecom-service-agent/blob/b0f55585ad7ed827fd74c3d0f228914adc72bbc1/app/evaluation/metrics.py)、[LICENSE](https://github.com/HuaiNan54321/ecom-service-agent/blob/b0f55585ad7ed827fd74c3d0f228914adc72bbc1/LICENSE)。这些是同一资料的实现核查，不另行增加篇数。

### 2. Building effective agents

- **标题与 URL**：[Building effective agents](https://www.anthropic.com/research/building-effective-agents)。来源：Anthropic 工程团队；页面标注 2024-12-19。
- **实际访问范围**：原 `/engineering/` 地址返回 308，跟随到 `/research/` 后取得正文；核读 workflows/agents 定义、routing、agents、客服实例与工具接口附录。页面同时提示部分工具背景已经变化；不以旧文中的模型示例做选型。
- **可支持的具体结论**：工作流使用预定义代码路径；Agent 由模型动态规划。Routing 将输入送往专属任务，也可以采用传统分类算法。文中建议从简单方案起步，复杂度应由可测的效果提升证明；执行过程从环境/工具结果取得事实，并设停止条件。
- **对本项目的建议**：六职责可以作为任务接口，不要求六个长期运行模型。FAQ、本人订单、确认取消和工单审核保留确定性流程；开放选购问答才考虑有限模型辅助。对混合问题先澄清优先级或列待办，不能让自由规划扩大权限。

### 3. Interrupts

- **标题与 URL**：[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)。来源：LangChain/LangGraph 官方文档。
- **实际访问范围**：取得正文，核读暂停/恢复、持久化、`thread_id`、节点重跑及中断前副作用的幂等要求；未安装或运行框架。
- **可支持的具体结论**：恢复依赖持久状态与同一 `thread_id`；恢复时节点从开头重跑，`interrupt` 前的代码可能再次执行。文中明确要求中断前副作用尽量幂等，并建议把副作用放到独立节点或批准之后。暂停/恢复本身不提供买家授权校验。
- **对本项目的建议**：沿用现有一次性取消确认与事务证据；未来退款/补发采用服务端保存方案、确认、重验、幂等执行、独立核验。工单等待不能靠一个进程内等待函数维持；恢复时重新查身份、订单状态、政策和确认期限，不复用过时许可。

### 4. Memory overview

- **标题与 URL**：[Memory overview](https://docs.langchain.com/oss/python/concepts/memory)。来源：LangChain 官方概念文档。
- **实际访问范围**：原 LangGraph memory 地址重定向到本页；取得正文，核读短期/长期记忆、命名空间、语义/情节/程序记忆及写入时机。
- **可支持的具体结论**：短期记忆属于线程状态；长期记忆跨线程并依自定义 namespace 保存。长历史可能造成干扰、延迟和成本；保存更多原始对话不保证更好上下文。
- **对本项目的建议**：把当前商品、已选订单、待补字段、已核验事实及待办保存在咨询状态；主动保存的偏好独立按买家作用域管理。摘要保留来源和时间，不替代下一次业务查询。文档中的 namespace 是存储机制，身份仍由商城会话确定；保留/删除期限按本项目约定验收。

### 5. Product data specification

- **标题与 URL**：[Product data specification](https://support.google.com/merchants/answer/7052112?hl=en)。来源：Google Merchant Center 官方帮助。
- **实际访问范围**：取得长文正文；核读基本商品数据、ID、商品/条目/变体定义，以及价格和可售状态要求；未逐项研究税费、监管或地区政策。
- **可支持的具体结论**：商品 ID 应唯一、更新时稳定；商品、feed 条目与变体是不同概念。价格和可售状态应与落地页及结账保持一致。关键原文为 “Keep the ID the same when updating your data”。
- **对本项目的建议**：推荐和对比输出绑定具体商品 ID、查询时间及属性依据；价格/库存从目录工具取，静态知识不能覆盖。先补属性完整度和数据校验，再优化推荐排序。未来如果引入多规格，要先扩展商品与库存模型，不能仅靠客服话术造出规格。

### 6. Size [size]

- **标题与 URL**：[Size [size]](https://support.google.com/merchants/answer/6324492?hl=en)。来源：Google Merchant Center 官方帮助。
- **实际访问范围**：取得正文，核读尺码字段、多个尺寸组成、`size_type`、`size_system`、`item_group_id` 和服装/鞋类示例。
- **可支持的具体结论**：尺码标签还受国家制度、版型和宽度等因素影响；多个尺寸组成需完整表达，尺码变体应作为独立条目并关联同组。文档没有提供“给定身高体重就能保证合身”的模型。
- **对本项目的建议**：在现有尺码表校验与显式单位测量之上，逐步补尺寸含义（人体尺寸/成衣尺寸）、单位、尺码制度、版型和来源版本；缺哪一维就问哪一维，重叠区间可展示多个匹配及差异。只有经确认的表支持建议，不能把网络经验当商品尺码依据。

### 7. About discounts

- **标题与 URL**：[About discounts](https://shopify.dev/docs/apps/build/discounts)。来源：Shopify 开发者官方文档。
- **实际访问范围**：取得正文，核读自动优惠/优惠码、访问 scope、GraphQL 折扣管理，以及 Order/Product/Shipping discount classes。另一个帮助中心“折扣组合”页面返回 403，未把其组合细节作为已读依据。
- **可支持的具体结论**：优惠既有自动触发，也有优惠码触发；需要满足条件，并分别作用到商品、整单或运费。折扣计算发生在购物车/结账流程；文本介绍活动不能证明买家当前购物车可享用。
- **对本项目的建议**：先将活动知识整理成生效时间、适用商品/渠道、人群、门槛、上限和叠加限制，再接独立资格/试算工具。回答区分“活动规则”“当前可用资格”“本次试算”，最终金额来自商城结算系统；没有接口时只解释有效规则或登记核实。

### 8. Fulfillment — GraphQL Admin API 2026-10

- **标题与 URL**：[Fulfillment](https://shopify.dev/docs/api/admin-graphql/2026-10/objects/Fulfillment)。来源：Shopify 官方 API 参考，固定 2026-10 版本。
- **实际访问范围**：取得正文，核读对象定义、访问 scope、`trackingInfo`、`events`、`estimatedDeliveryAt`、`deliveredAt`、状态与履约商品关联；未调用 API。
- **可支持的具体结论**：一个订单可以有多次履约；物流单号/链接、事件历史、预计到达和实际到达是不同字段。预计送达字段可为空，持有运单号不代表已经取得运输事件。
- **对本项目的建议**：继续准确展示已保存物流。未来接实时物流时按包裹建模，保存事实来源、事件发生/获取时间与更新时间，缺少 ETA 就明确未知；不能把整个订单的发货状态当每件商品已签收。外部接口的 scope 不能替代本商城买家归属检查。

### 9. Apps in returns

- **标题与 URL**：[Apps in returns](https://shopify.dev/docs/apps/build/orders-fulfillment/returns-apps)。来源：Shopify 开发者官方指南。
- **实际访问范围**：取得正文，核读退货含义、生命周期、逆向履约、状态变更 mutation 及 webhooks；未执行退货操作。
- **可支持的具体结论**：退货涉及资格、批准、寄回、验货/回库、换货和退款等不同动作；`REQUESTED`、`OPEN`、`CLOSED`、`DECLINED`、`CANCELED` 分别由不同动作触发。页面还说明 API 2025-07 引入 return processing，升级实现需要遵守版本变化。
- **对本项目的建议**：在已有服务申请和进度查询之上，为真实售后定义业务动作及其证据，而非把 `SupportCase.resolved` 当退款到账。按“登记→审核→待买家补充/寄回→执行→核验”拆分任务，具体流程与资格由商城政策决定，不照搬 Shopify 状态和退货政策。

### 10. Manage reverse deliveries

- **标题与 URL**：[Manage reverse deliveries](https://shopify.dev/docs/apps/build/orders-fulfillment/returns-apps/manage-reverse-deliveries)。来源：Shopify 开发者官方指南。
- **实际访问范围**：取得正文，核读要求、创建逆向配送、查询、处置和限制；确认文中提到旧处置 mutation 的废弃，未沿用其旧调用方式。
- **可支持的具体结论**：单次退货可以拆成多个逆向包裹。接口虽然返回承运商、单号和链接，却明确不能据此查询是否在途、面单是否扫描或是否送达。原文：“an app can't query if an item is in transit”。
- **对本项目的建议**：把“有退货运单资料”“承运商运输事件”“仓库验收”分别建模。创建退货面单或录入单号不能触发“已收到退货/退款处理中”；需要承运商和仓库的独立事实接口，未接通继续如实标记。

### 11. Fin Custom Helpdesk Integration API

- **标题与 URL**：[Fin Custom Helpdesk Integration API](https://developers.intercom.com/docs/guides/fin-custom-helpdesk)。来源：Intercom 官方开发者文档。
- **实际访问范围**：取得正文，核读核心对象、同步流程、人工交接、重试策略；并核读同一 API 的 Conversations 对象说明。没有接入 Fin 或发送消息。
- **可支持的具体结论**：该集成需由自己的系统提供会话读写端点，并通知变化；Fin 无法回答时通过更新会话、将 `assignee_id` 置空表示退出处理，之后由 helpdesk 等人工接起。Conversations 说明已分配人工的会话通常不再由 Fin 处理。置空本身不是人工已接受。
- **对本项目的建议**：在现有工单中明确队列等待、人工接手、人工回复、等待买家、审结/重开；自动处理和人工回复不能竞争同一案件。跨系统交接包包含诉求、已核验事实/时间、已执行动作/证据、未完成事项及历史共享范围。保留本地“等待管理员接手”的准确文案。
- **辅助核查**：[Conversations](https://developers.intercom.com/docs/guides/fin-custom-helpdesk/api/conversations)。同一集成的协议核查，不另计一篇。

### 12. WeKnora（维娜拉）README_CN

- **标题与 URL**：[固定版本 README_CN](https://github.com/Tencent/WeKnora/blob/e1f9a6166a593a4804a2f99f1d942919c9cc8ea7/README_CN.md)。来源：腾讯官方 `Tencent/WeKnora` 仓库。
- **实际访问范围**：通过 `gh api` 固定 `e1f9a6166a593a4804a2f99f1d942919c9cc8ea7` 并取得 README 正文，核读项目介绍、检索/引用、分块维护、权限与集成、v0.8.2/v0.8.3 说明；未部署、未审计全部实现。
- **可支持的具体结论**：README 声明支持混合检索、原文引用、可编辑/回滚分块、数据源同步与空间权限；v0.8.2 说明 MCP 端点有独立令牌、知识范围和限流，并指出旧 Python MCP Server 已弃用。这些是该版本维护者的功能说明，不是本项目实测结果。
- **对本项目的建议**：未来接回真实 WeKnora 时固定版本，先做只读候选检索与原文定位，逐项验收删除传播、范围约束、冲突和不可用。继续由商城登记裁决政策权威；不因其具有浏览器、沙箱和外部 MCP 能力就把这些工具开放给客服。

### 13. Change and delete detection using indexers for Azure Storage

- **标题与 URL**：[Changed and Deleted Blobs — Azure AI Search](https://learn.microsoft.com/en-us/azure/search/search-how-to-index-azure-blob-changed-deleted)。来源：Microsoft Learn 官方文档；正文主题为变更和删除检测。
- **实际访问范围**：取得正文，核读自动变更检测、软删除、孤儿索引、首次索引配置、保留期和恢复后的重新索引条件。
- **可支持的具体结论**：源文件删除不会自动保证索引文档删除；未在首次索引时配置删除策略可能留下孤儿文档。软删除保留窗口必须足够让索引器读到删除标志；恢复源文件也不一定触发重新索引。
- **对本项目的建议**：本地已有有效期和撤回过滤；接入外部检索/缓存后需建立知识 ID、版本、撤回状态的同步及核验链路。索引只给候选 ID，发答前回查商城权威记录；以“撤回后立即再问”“旧引用回放”“索引延迟”验收。Azure 的具体设置不能被宣称为 WeKnora 已有能力。

### 14. Security Best Practices — MCP 2025-11-25

- **标题与 URL**：[Security Best Practices](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices)。来源：Model Context Protocol 官方文档，固定协议版本 2025-11-25。
- **实际访问范围**：旧 `/specification/` 地址 308 后取得正文；核读 confused deputy、逐客户端同意、token passthrough、audience、SSRF 和权限最小化。
- **可支持的具体结论**：MCP 规范禁止把未经本服务正确校验的 token 直接透传下游；MCP 服务不得接受并非签发给自己的 token。接第三方授权时，还需防止代理成为 confused deputy，并限定请求客户端及 scope。
- **对本项目的建议**：当前进程内工具继续从服务器会话派生身份，不引入通用代理。未来远程 MCP 或渠道 Adapter 使用各自令牌与权限范围，在服务端保存秘密；平台买家标识、商城买家和店铺授权必须显式映射。此文研究远程授权边界，不要求为了内部工具强加 OAuth。

### 15. Task Schema and Evaluation — τ-bench

- **标题与 URL**：[Task Schema and Evaluation](https://github.com/sierra-research/tau2-bench/blob/0c69df456a96aa76a1162591574dad9c427a34d7/docs/evaluation.md)。来源：Sierra 官方研究仓库。
- **实际访问范围**：旧 `tau-bench` README 明确提示任务过时，顺着维护者链接核实 `tau2-bench` 当前快照 `0c69df456a96aa76a1162591574dad9c427a34d7`；读取当前 README、评测文档、evaluator 和 retail policy。未运行模拟用户或模型评测。仓库 README 在该快照称 τ-bench 2.0，不把旧 τ²/τ³ 名称或榜单当当前结果。
- **可支持的具体结论**：最终 reward 由任务 `reward_basis` 指定；`actions` 通常是生成目标数据库状态的一条参考轨迹，并非唯一正确调用序列。文档明确 retail 等领域不以 ACTION 奖励强制匹配轨迹；环境终态、沟通内容和动作检查是不同维度。
- **对本项目的建议**：用合成订单和本商城规则写任务，检查最终状态、证据、权限与必要告知，允许等价正确路径。取消/地址等敏感步骤仍设必须满足的硬约束。retail policy 的“邮箱或姓名+邮编认证”、退款时限和权限**与本项目 ADR 不同，不采用**，更不能导入商城政策库。
- **辅助核查**：[评测实现](https://github.com/sierra-research/tau2-bench/blob/0c69df456a96aa76a1162591574dad9c427a34d7/src/tau2/evaluator/evaluator.py)、[测试领域政策](https://github.com/sierra-research/tau2-bench/blob/0c69df456a96aa76a1162591574dad9c427a34d7/data/tau2/domains/retail/policy.md)。属于同一 benchmark 资料单元。

### 16. Demystifying evals for AI agents

- **标题与 URL**：[Demystifying evals for AI agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)。来源：Anthropic 工程团队；页面标注 2026-01-09。
- **实际访问范围**：原工程地址 308 后取得正文，核读 task/trial/transcript/outcome、评分类别、pass@k/pass^k、数据集起步、平衡正反例及人工复核；未运行文中框架。
- **可支持的具体结论**：执行记录与实际结果不同；多次尝试至少成功一次的 pass@k 和每次均成功的 pass^k 回答不同问题。文章建议从真实失败中的 20–50 个简单任务起步，并同时测试“应该做”和“不应该做”。该数量是方法建议，不是本项目验收标准或统计充分性证明。
- **对本项目的建议**：先整理小规模离线中文多轮场景集，覆盖已有边界与常见失败；每个案例有可检查的期望状态/禁止动作。合成 transport 与确定性评分先执行，主观表达可人工复核；真实模型稳定性测量、LLM judge 和成本另行授权，本次不调用。

### 17. Semantic conventions for generative client AI spans

- **标题与 URL**：[GenAI spans 固定版本](https://github.com/open-telemetry/semantic-conventions-genai/blob/9ffc7e00c639be7712e544e3e54331e885dccf84/docs/gen-ai/gen-ai-spans.md)。来源：OpenTelemetry 官方 `semantic-conventions-genai` 仓库。
- **实际访问范围**：旧官方属性页显示 GenAI 约定已迁移，跟到维护仓库并固定 `9ffc7e00c639be7712e544e3e54331e885dccf84`；取得 spans、agent spans、metrics 正文，核读工具执行、错误、耗时和内容记录章节。规范状态为 **Development**，未接入遥测平台。
- **可支持的具体结论**：工具名、调用标识、操作、错误等可关联执行；工具参数/结果是 Opt-In，指令、输入和输出默认不应采集。文档明确默认模式是 “Don't record instructions, inputs, or outputs”。重试也属于一个逻辑操作的耗时范围。
- **对本项目的建议**：在现有白名单服务事件上补关联编号、工具/角色/知识版本、耗时与错误分类；运行诊断不保存完整订单、地址、token、对话或确认凭据。业务执行证据和遥测分开保存；工具 span 成功只能说明协议执行成功，不能证明退款到账。采用时锁定约定版本。
- **辅助核查**：[Agent spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/9ffc7e00c639be7712e544e3e54331e885dccf84/docs/gen-ai/gen-ai-agent-spans.md)、[Metrics](https://github.com/open-telemetry/semantic-conventions-genai/blob/9ffc7e00c639be7712e544e3e54331e885dccf84/docs/gen-ai/gen-ai-metrics.md)。属于同一遥测约定资料单元。

### 18. Build your own reports

- **标题与 URL**：[Build your own reports](https://developers.intercom.com/docs/build-an-integration/learn-more/rest-apis/build-your-own-reports)。来源：Intercom 官方开发者指南。
- **实际访问范围**：取得正文，核读回复/首次分配/关闭时间、reopened conversations、CSAT 与排除 preview 会话的建议。页面部分示例存在 TODO 和字段描述不一致，未把示例直接当可执行报表规范。
- **可支持的具体结论**：首次回复时长与首次分配时长不同；会话可以多次关闭，重开另有统计。AI CSAT 以已有评分会话为分母，4–5 分为正向；预览和工作流测试应从真实业务报表排除。不能对回复时间戳直接求中位数当耗时。
- **对本项目的建议**：保留当前“买家明确标记解决/有反馈”的解决率口径，同时展示反馈覆盖率和样本数；补人工等待到接手、接手到回复、重开率。合成演示、自动化测试与真实使用分开统计；无反馈不等同未解决，更不能当已解决。各指标采用本项目明确事件定义，而非照抄该页全部公式。

### 19. API调用方法详解

- **标题与 URL**：[API调用方法详解](https://developer.alibaba.com/docs/doc.htm?articleId=101617&docType=1&treeId=796)。来源：淘宝开放平台官方文档；页面标注更新 2026-04-24。
- **实际访问范围**：取得正文，核读调用入口、公共参数、授权 session、签名、注意事项与限流/权限/无效 session 错误。未申请应用或调用订单、聊天 API。
- **可支持的具体结论**：TOP 使用应用 AppKey；标明需要授权的 API 必须传授权 session；请求需签名。页面区分应用流量、单接口流量、开发者权限和无效/过期 session 等错误。
- **对本项目的建议**：淘宝 Adapter 单独封装应用/店铺授权、签名、权限和限流，并建立外部 ID 到本地对象的受控映射。这个通用调用指南**不能证明拥有千牛消息权限、可获取某店铺订单或已经接入淘宝客服**；这些要逐个核实目标 API、资质与真实回执。

### 20. 企业客服管理接入方案

- **标题与 URL**：[企业客服管理接入方案](https://open.douyin.com/platform/resource/docs/ability/enterprise-account-open-ability/enterprise-customer-service-solution)。来源：抖音开放平台官方文档。
- **实际访问范围**：取得可读正文，核读功能、适用场景、授权及权限范围；正文没有具体抖店订单 API。未申请权限或发送私信。
- **可支持的具体结论**：文档明确“提供的形式为接口，而不是具体的客服平台”；能力涉及企业号客服账号、会话及进入/退出提示，会话应只有一名客服介入。使用限制是需用户授权，针对审核通过的企业号，权限名为 `enterprise.im`。
- **对本项目的建议**：将企业号私信和抖店交易客服视为不同接入范围；企业号获批不能代替店铺订单授权。渠道状态分别表达授权、入站消息、出站回执、人工会话归属与交易数据能力，全部有证据后才标为已接入。

## 功能映射与可实施结论

表中验收是后续实施建议，不表示本研究已执行测试。按收益与依赖排序，优先利用现有商城能力。

| 功能/差距 | 来源 | 结合当前实现的具体建议 | 最小可检查结果 |
|---|---|---|---|
| 入口路由与任务闭环 | [1][2][4][16] | 当前路由增加离线混淆矩阵和多轮任务标注；区分开始、补字段、改条件、查进度、撤回诉求。多意图只读问题可分步，写动作逐一显式确认。 | “先别退，查一下物流”“不是退款，是换码”“不需要人工”不误触发；追问补信息不重复建申请。 |
| 售前推荐 | [4][5][12] | 使用现有预算/类别/场景状态与推荐工具，解释筛选条件、候选和未满足的约束；用户本轮修正覆盖旧偏好。 | 推荐均为当时上架且有目录依据的商品；超预算、缺属性和无合适候选能说明原因；不声称商城保证适合。 |
| 商品对比 | [5][6] | 固定比较的商品 ID，同名要消歧；按同一维度、单位和有效来源对齐；未知字段明确缺失。 | 不以缺资料推断“不具备”；价格库存来自目录；切换比较对象后旧商品属性不混入。 |
| 尺码 | [6][4] | 延续已实现的分轮测量和单位校验；补版型、尺码制度、尺寸含义及来源元数据；不持久化未同意的身体测量。 | 缺维度时针对性追问；不同商品不套用上一张表；边界/重叠/单位换算可检查；所有建议可回指当前商品尺码表。 |
| 活动优惠 | [7][5] | 先提高有效活动条目覆盖，再独立实现资格/试算接口，供受控只读工具使用。 | 列出适用时间、商品、门槛和排除条件；规则解释与实际试算分开；没有当前依据就不保证能用券或给优惠金额。 |
| 订单物流 | [8][10][14] | 保留本人订单显式选择；接承运商前继续标注已保存资料；接入后分包裹存事件、时间、来源与过期状态。 | 无轨迹时不编造 ETA；空值不等于运输异常；旧事件不能让状态回退；不泄露他人订单。 |
| 售后、退款、补发、发票 | [3][9][10][15] | 现有登记与进度工具保留；真实业务建立动作状态、幂等键、执行证据与查询接口，再增加受控执行工具。 | 人工“已处理”不等于退款到账；超时先查结果；重放不重复执行；申请数量、商品和资格可核验。 |
| 人工交接与投诉 | [11][20][18] | 当前工单基础上补等待/接受的时间事件与会话负责人；交接后自动回复与人工办理有明确边界；共享历史持续遵守买家选择。 | 创建、接手、回复、解决分别展示；没人接手时不说“已有人处理”；投诉不自动授予赔偿。 |
| 知识版本与撤回 | [12][13][14] | 当前数据库有效期与冲突门作为最终权威；未来外部索引返回候选 ID，发答前核验有效版本；缓存按版本失效。 | 退役/到期/未来版本、商品下架、同主题冲突、旧索引和旧引用回放都不能输出失效承诺。 |
| 短期上下文与偏好 | [4][6][14] | 咨询状态记录待办、选中对象、补齐字段和事实时间；偏好独立、可改可删；订单事实需重新查询。 | 退出/换账号失效；删除偏好后不再影响推荐；历史用户文本与摘要不能提供身份或确认权限。 |
| 审计与服务指标 | [17][18][15] | 在现有事件和口径上补版本、关联与耗时；协议正常返回、正确回答、业务完成、用户确认分别计数；展示反馈覆盖率。 | 能解释每个分子/分母及统计窗口；无数据为空；演示不混入真实经营数据；诊断日志无完整对话和秘密。 |
| 离线评测 | [1][15][16] | 构造中文任务集，分路由、依据、执行、交接和渠道；确定性状态评分优先，表达人工复核；保留独立验证集。 | 多次重复稳定、硬性违规为零；任务成功不只靠关键字或固定工具顺序；明确样本、版本、transport 与运行范围。 |
| 多平台与通知 | [19][20][14] | 保留五渠道真实状态；每个平台单独 Adapter，明确消息和交易权限；事件回执、签名、重复处理、重连和撤权分别验收。 | 配置欢迎语不变为已连接；渠道买家不靠邮箱自动合并；平台回执、订单读取与人工会话切换均有独立证据。 |

## 建议落地顺序与任务样本

### 第一批：把现有功能验成连贯体验

先用已有商品、服务进度、尺码和工单能力构造 **30 个合成多轮任务作为起始提案**：入口/修正 6、推荐/对比/尺码/活动 8、订单/服务进度/售后 6、人工/知识/记忆 6、审计/渠道真实性 4。每个任务包含起始身份、当前知识版本、对象状态、用户各轮输入、允许/禁止动作、预期最终状态与必须告知内容。30 是便于开工的规模，不宣称覆盖充分；已有测试应复用，避免只重复函数内部逻辑。[15][16]

关键样本应包含：

- “想退款”→明确选订单→“先不要退，快递到哪里”；核查只读查询与待办切换，不新建退款申请。
- “这件和那件哪个适合通勤”→澄清具体商品→“预算改成 200”；核查商品消歧、预算更新和缺属性说明。
- 选商品→只报身高→补体重（斤）→切换商品；核查分轮测量、换算、当前尺码表、旧表隔离及缺维度提示。
- 活动已到期、活动条目冲突、没有购物车资格接口；应解释缺少何种依据，不承诺可用或凭空计算到手价。
- 查询退款/补发进度时工单 `resolved`，但执行系统 `not_connected`；应如实说明，不能承诺到账、已寄出或已开票。
- 人工交接→队列无人接手→管理员接手→回复→买家补充重开；分别核查状态、归属、通知及可见上下文。
- 知识发布→回答→退役→再次查询/回放旧引用；失效条目不能再次成为当前承诺。
- 切换买家、删除偏好、否定转人工、工具结果夹带指令；不沿用旧权限或把数据当指令。
- 非 storefront 渠道仅保存配置；保持未接入，不生成虚假入站消息或“已连接”指标。

本批先使用合成 transport、受控业务测试与人工阅读，不调用付费模型。需要真实模型质量测量时，再单独确认场景、数据、预算和版本；本文不选择模型，也未测量 token 成本。[16]

### 第二批：业务事实与运营资料补齐

商品侧优先覆盖热门商品的属性、用途、尺码表与差异维度，发布前校验单位和来源；活动侧整理可判定的资格字段。每条商品建议都应说明“哪些来自目录、哪些来自哪个有效知识版本、哪些未知”。这些资料必须由商城运营确认，外部攻略只帮助设计字段。[5][6][7]

售后侧在已有服务申请/进度之上接一类真实执行闭环时，应同时具备方案、必要确认、资格/订单重验、幂等执行、结果查询、事务或外部回执证据和超时恢复。建议先选业务依赖最清楚的一类；退款资金、补发、发票不可因工单可审结而视为开通。[3][9][10]

### 第三批：检索与外部渠道逐项接入

真实 WeKnora 先按固定版本接只读检索，核验权限、撤回、过期、冲突、无匹配和不可用语义，再讨论召回或重排提升。相似度的提高不能替代权威性。[12][13]

渠道需要“文档明确支持→应用/店铺获批→令牌与 scope 有效→入站/出站/人工交接/交易读取分别验收”的证据。淘宝通用 API 文档和抖音企业号方案分别只能证明其所述范围；京东、拼多多和抖店此次没有取得足以确认客服端点的完整官方正文，具体方法名、消息权限、资质与限额保留待核实，不能从第三方 SDK 推断已经支持。[19][20]

## 评测、审计与指标的建议口径

现有指标已经有明确定义，应在其上补维度，不重命名成未经测量的“自动解决率”。[18]

| 指标 | 建议定义与限制 |
|---|---|
| 路由质量 | 有人工标注的离线任务逐类 precision/recall、混淆矩阵；多轮按任务流转判对。规则 confidence 不作为已校准概率。 |
| 任务成功 | 达到案例规定最终状态、必要告知且未触发禁止动作的任务数 / 可执行任务数；知识缺失时正确拒绝或澄清也按该案例预期评分。 |
| 业务执行成功 | 有可核验业务证据的成功动作 / 已尝试执行动作；与工具正常返回率、人工审结率分开。 |
| 有效依据 | 含事实/政策结论中可追溯到当时有效来源的结论数 / 需要依据的结论数；不仅看检索是否命中。 |
| 反馈解决率与覆盖率 | 保留“明确反馈解决 / 有反馈”；另列“有反馈咨询 / 符合反馈条件咨询”，缺反馈不推断解决。 |
| 人工等待与重开 | 从升级/入队到明确接手的时长；从接手到首条人工回复的时长；在约定观察窗内重开数 / 已审结案件数。跨窗口案件另说明归属。 |
| 可靠性 | 需要真实随机模型测量时关注重复任务全成功的 pass^k 与样本量；不以多试几次至少成功一次掩盖不稳定。确定性用例重复运行不等于模型可靠性研究。 |
| 诊断 | 关联咨询、角色/提示版本、工具名、结果类别、知识 ID/版本、耗时和错误类型；自由文本、秘密与完整个人信息不进入默认日志。 |

任务评分中的具体政策、认证方式和确认程序必须以本项目为准。τ-bench 的测试商店采用邮箱/邮编定位用户，不能改写本商城“仅服务器会话授权”；框架的 `interrupt` 或模型说“用户已同意”也不能替代现有取消确认卡和一次性凭据。[3][14][15]

## 小红书与其他访问限制：不计入 20 份主体

### 小红书用户原创笔记

本次实际尝试了以下检索，不填写不存在的笔记标题、作者或发布日期：

- `site:xiaohongshu.com/explore "客服" "Agent"`
- `site:xiaohongshu.com/discovery/item "AI客服"`
- `site:xiaohongshu.com "智能客服" "笔记" "淮南"`
- `"小红书" "电商客服Agent" "淮南"`
- `"xiaohongshu.com/explore/" "AI" "客服"`
- `"xiaohongshu.com/discovery/item/" "客服" "智能"`

返回结果没有取得可确认的相关用户笔记原文；主要为官方课程、招聘、GitHub 项目或第三方收录。第三方转载和作者 README 中“在小红书更新”的自述都不等同读到小红书原文。没有编造笔记 ID、绕过登录、安装抓取工具或使用第三方账号。

| 实际访问对象 | 实际结果 | 可使用范围 |
|---|---|---|
| [小红书公开搜索页：电商客服 Agent](https://www.xiaohongshu.com/search_result?keyword=%E7%94%B5%E5%95%86%E5%AE%A2%E6%9C%8D%20Agent&source=web_explore_feed) | 无认证 HTTP 200，重定向到带尾斜杠路径；只得到搜索标题、导航和页脚，未得到笔记列表、作者或正文。 | 只证明本次未取得原文；不计资料数。 |
| [官方电商学习中心课程页 A](https://school.xiaohongshu.com/lesson/normal/d02dfddb19e4459b81cba7fa372e9cf6) | 搜索返回显示《商家智能客服机器人使用指南》及摘要；直接 HTTP 200 仅有“小红书电商学习中心”外壳。 | 课程标题只是搜索结果所示名称，未核读课程正文；摘要中的功能不作为本文结论依据。 |
| [官方电商学习中心课程页 B](https://school.xiaohongshu.com/lesson/normal/2ff1324e622d42cbbf66f1d6ae2f38d5) | 搜索返回显示《AI智能客服推广手册》及摘要；直接 HTTP 200 仍只有学习中心外壳。 | 同上；不能称已读官方课程，更不是用户原创笔记。 |
| [小红书开放平台](https://open.xiaohongshu.com/rest) | HTTP 200，仅得到“小红书”页面标题。 | 不能确认客服 API、授权 scope 或订单权限。 |
| [官方招聘页 21002](https://job.xiaohongshu.com/campus/position/21002)、[22481](https://job.xiaohongshu.com/campus/position/22481) | 搜索摘要涉及客服 Agent；直接 HTTP 200 只有“小红书”页面壳。 | 不把岗位描述当作平台已交付能力或独立技术资料。 |

**访问限制的准确表述**：WebFetch 对小红书和若干其他公开域名统一返回安全校验失败；使用普通无认证 HTTP 后，小红书返回页面外壳。现有证据不能分辨究竟由前端渲染、登录要求、反爬还是工具环境造成，故不武断写成“被反爬封禁”。本次可以报告“小红书检索尝试与正文不可得”，不能报告“读了若干小红书笔记”。为保持结论可核实，20 份主体全部由可核读公开来源补足；这不代表已完成小红书笔记全文研究。

### 其他被排除或限定的入口

| 入口 | 实际结果及处理 |
|---|---|
| [Shopify 折扣组合帮助](https://help.shopify.com/en/manual/discounts/discount-combinations) | HTTP 403；主体第 7 项改用开发者折扣指南，仅采用已取得正文的规则类型，不声称核实组合细节。 |
| [Zendesk Ticket Metrics](https://developer.zendesk.com/api-reference/ticketing/tickets/ticket_metrics/)、[metric event types](https://developer.zendesk.com/documentation/ticketing/reference-guides/ticket-metric-event-types-reference/) | HTTP 403；未计主体，指标结论采用实际可读的 Intercom 文档并标明其局限。 |
| [京东宙斯用户授权入口](https://jos.jd.com/commondoc?listId=306) | HTTP 200 只有开发者中心页面壳；搜索摘要不能证明当前迁移后接口和权限可用。未计主体。 |
| [抖店授权介绍](https://op.jinritemai.com/docs/guide-docs/133?docLabel=1) | HTTP 200 只有“抖店开放平台”；不能用主体第 20 项企业号私信方案替代店铺交易客服文档。 |
| [拼多多授权文档线索](https://open.pinduoduo.com/application/document/browse?idStr=BD3A776A4D41D5F5) | 地址来自检索线索；直接 HTTP 200 只有“拼多多 开放平台”。未确认正文标题、参数或权限，不计主体。 |
| [旧 τ-bench](https://github.com/sierra-research/tau-bench) | README 明确说任务过时；转到维护者指定的 `tau2-bench` 并使用固定快照第 15 项，不用旧榜单作当前表现证明。 |
| [旧 OpenTelemetry GenAI 属性页](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/) | 正文提示迁移；第 17 项跟到当前维护仓库并固定版本，不把迁移页与新仓库重复计数。 |

## 研究完成范围

正文来源编号 1–20，共 20 份；附属文件用于交叉核查而不增加数量；小红书用户原创全文 0 份，官方课程全文 0 份。外部请求仅使用公开检索词、公开 URL 与指定公开仓库，未向外部发送本地源码、买家资料或凭据。未运行应用、迁移、测试、上游脚本或真实付费模型，本文建议也不表示真实业务系统或平台已接通。

[1]: https://github.com/HuaiNan54321/ecom-service-agent/blob/b0f55585ad7ed827fd74c3d0f228914adc72bbc1/README.md
[2]: https://www.anthropic.com/research/building-effective-agents
[3]: https://docs.langchain.com/oss/python/langgraph/interrupts
[4]: https://docs.langchain.com/oss/python/concepts/memory
[5]: https://support.google.com/merchants/answer/7052112?hl=en
[6]: https://support.google.com/merchants/answer/6324492?hl=en
[7]: https://shopify.dev/docs/apps/build/discounts
[8]: https://shopify.dev/docs/api/admin-graphql/2026-10/objects/Fulfillment
[9]: https://shopify.dev/docs/apps/build/orders-fulfillment/returns-apps
[10]: https://shopify.dev/docs/apps/build/orders-fulfillment/returns-apps/manage-reverse-deliveries
[11]: https://developers.intercom.com/docs/guides/fin-custom-helpdesk
[12]: https://github.com/Tencent/WeKnora/blob/e1f9a6166a593a4804a2f99f1d942919c9cc8ea7/README_CN.md
[13]: https://learn.microsoft.com/en-us/azure/search/search-how-to-index-azure-blob-changed-deleted
[14]: https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices
[15]: https://github.com/sierra-research/tau2-bench/blob/0c69df456a96aa76a1162591574dad9c427a34d7/docs/evaluation.md
[16]: https://www.anthropic.com/research/demystifying-evals-for-ai-agents
[17]: https://github.com/open-telemetry/semantic-conventions-genai/blob/9ffc7e00c639be7712e544e3e54331e885dccf84/docs/gen-ai/gen-ai-spans.md
[18]: https://developers.intercom.com/docs/build-an-integration/learn-more/rest-apis/build-your-own-reports
[19]: https://developer.alibaba.com/docs/doc.htm?articleId=101617&docType=1&treeId=796
[20]: https://open.douyin.com/platform/resource/docs/ability/enterprise-account-open-ability/enterprise-customer-service-solution
