# #3 最终验收核对

核对日期：2026-10-23。原始工单：[客服03](https://github.com/LazyYang-v/docs/issues/3)。本轮按用户选择完成受控演示范围的审查修复并保存验证证据，保持工单开启。通过gh读取确认前置[#1](https://github.com/LazyYang-v/docs/issues/1)当前为CLOSED。

## 结论及适用范围

五条Acceptance criteria已在本地受控虚构商品范围完成A和B实现及所列验收。Phase A支持匿名访客确定性只读查询；Phase B支持有限中文整句理解、本地澄清、真实序列化MCP协议边界和合成模型工具循环。认证用户仍限两名专用演示买家；匿名路径仅访问fixture商品，无政策、订单或写操作。

B仅支持已列明的受控中文语法，不是开放域NLU；MCP为进程内ASGI HTTP往返，不是独立MCP服务或WeKnora接入。真实提供方兼容性/网络故障未验证，生产真实模型调用保持关闭。政策问答归#4并明确不可用；真实订单及确认凭据契约未修改。

因此A/B源码验收通过不等于生产部署或真实提供方验收。关闭前仍须完成C的持久化原子请求数/人民币上限、核价及请求方案，经用户查看A/B证据并明确批准后，在隔离演示环境进行低量真实验证，完成最终错误降级/安全/桌面移动矩阵及证据发布。C未授权前不得真实调用或关闭#3。

## Phase B 最新证据与范围（覆盖下文旧阶段结论，2026-10-23）

B现已实现本地整句商品语法、实际序列化MCP和完整合成模型工具循环；下文“未实现自由文本/MCP/循环”保留为历史A阶段观察。限制是整句受控语法，不提供任意语言/模糊名称理解，未知/歧义/混入私人文本本地澄清，0模型调用。仅本地ASGI HTTP MCP2025-03-26，无独立MCP进程、公网服务或真实模型业务验证。生产真实provider始终关闭；C未执行，真实调用累计0、金额0。

A后续独立修复f13a47e已合并：同页所有CSRF bootstrap与POST/续期串行，避免GET轮换使并发咨询令牌失效。真实Chrome受控交错先RED（rotation3而非2）后GREEN，完整浏览器13/13；不改服务端身份契约，不自动重放POST。

| B要求 | 实际证据 | 限制 |
|---|---|---|
| 匿名桌面/移动整句列表、名称价格/库存及复合问题 | test_whole_sentence_product_questions_and_local_clarification；test_customer_service_browser_queries_real_isolated_catalog，真实Chrome→messages→ASGI MCP→真实shop_test→合成exchange+真实ledger，桌面/移动各2响应，共4合成响应 | 中文完整名称及受控句式；非开放NLU |
| 实际MCP具名工具与严格边界 | 初始化、通知202、list仅2工具、call真实DB；额外SQL/未知工具/方法/version/bool ID拒绝API测试；result严格envelope/data验证、isError检查 | in-process HTTP无socket/外部端点；不宣称WeKnora商品服务 |
| 完整工具循环及隐私 | tool_calls→MCP→sanitized tool result→final JSON；重放不再执行；恶意ID/alias/schema/admin拒绝；原文/name/UUID/page/cookie/私人哨兵不进入exchange及安全日志 | call ID只接受call_1..4；模型list仅{}，当前轮仅选定商品alias |
| 期限/尝试/预算 | 原transport/model_limits/model_budget真实DB回归；匿名product_only真实共享账本、30分钟绝对期、会话/部署quota；4次/45秒、2商品尝试含重试；2 worker/2槽、90秒TTL、usage latch/迟到不退款 | ASGI受控DB读取靠statement_timeout；不提供任意同步Python函数强制取消，不证明远端停止 |
| 消息生命周期 | 专用session advisory连接跨编排，持久claim先提交，短事务避免auth FOR UPDATE与budget FOR SHARE自锁；交付重新校验，未知claim重放425 | 崩溃未知结果保守保留，用户可发新message_id，无自动恢复重执行 |
| 降级/政策 | 模型后续失败保留已核验partial；无事实503；政策/检索明确不可用，不注册政策或订单工具 | 实际模型提供方超时/网络故障未调用验证；合成及既有transport超时测试覆盖本地边界 |

本轮最终执行：`SHOP_RUN_BROWSER_TESTS=1 uv run --project backend python -I /tmp/shop-phase-a-tests.py backend/tests -q`：258 passed、2 warnings、54.87s。helper仅子进程授权127.0.0.1:55445/shop_test与reset；全套含真实浏览器。此前目标套83 passed，扩展咨询32 passed；本轮先RED后GREEN证据包括整句API、MCP模块缺失及复合问题未触发exchange。不重复计数为新增验收量。

前端模拟API套：`npx playwright test e2e/customer-service.spec.ts --reporter=line`：最终13 passed（13.8s）；`npm run build`通过，`git diff --check`通过。真实截图`/tmp/shop-phase-b-desktop.png`、`/tmp/shop-phase-b-mobile.png`含虚构名称/129.00/24和请求标识/时间，截图在私人哨兵输入前保存。安全日志集成断言仅request_id/tool/error/duration_ms/count/recorded_at字段，无原文、身份、密码或测试秘密。

全套首次256 passed/1 failed/1 teardown error，已修复合成测试close接口及跨集成账本保留计数假设后得到上述最终258通过；未隐藏失败或声称外部/付费验证。无开发/演示库操作、无部署、无外部Issue写入。尚未执行C官方价格复核/请求金额持久化预留；必须用户看A/B证据后明确确认，≤200累计请求且≤20元，任一达到停止。

## B审查后修复验证（2026-10-23）

独立审查3项均修复：clarification也提交持久claim/result，22次相同重放保持原response且不扣新quota，同ID换正文409；11件真实fixture的模型list调用不再漏掉第11件（内部page_size20）；MCP受控错误码保持资源不可访问/非法参数/依赖失败/超时区别，模型model_unavailable、政策policy_unavailable，浏览器对应提示不同。共享绝对deadline的可协作挂起ASGI协议测试0.03秒上限触发mcp_timeout，非任意阻塞线程终止证明。

修复前RED：clarification重放产生新request_id/时间；11fixture请求503。修复后：`uv run --project backend python -I /tmp/shop-phase-a-tests.py backend/tests/test_customer_service_consultations.py backend/tests/test_customer_service_model_transport.py backend/tests/test_customer_service_model_budget.py -q`：75 passed、2 warnings、20.60s。`npx playwright test e2e/customer-service.spec.ts --reporter=line`：14 passed、15.3s（含新增4错误类别显示）；`SHOP_RUN_BROWSER_TESTS=1 uv run --project backend python -I /tmp/shop-phase-a-tests.py backend/tests/test_customer_service_browser.py -q`：1 passed、2 warnings、3.30s，真实桌面/移动截图已更新。258全套通过是前一B提交结果，本次只运行受影响链路回归，不冒充新全套。临时Vite使用TaskStop回收，无保留服务器。

累计真实提供方请求0、金额0，C未执行。仍仅整句受控语法及in-process ASGI HTTP；无公网/独立MCP进程/真实提供方验证。

## B最终超时分类补正（2026-10-23）

仅补正残余商品MCP超时分类：`QueryDeadline.check/apply`期限耗尽抛出专用`QueryDeadlineExceeded`（仍属`CustomerServiceUnavailable`）；MCP将其及真实`DBAPIError.orig.sqlstate == '57014'`映射为`mcp_timeout`。普通不可用异常和其他SQLSTATE不按消息文本猜测超时；错误响应仍只含固定文案/允许错误码，不带数据库语句、异常详情或身份。商品读取原有最多2次尝试（含重试）未改变。

先RED后GREEN：`test_mcp_statement_timeout_preserves_category_and_two_attempt_budget`在真实授权PostgreSQL中每次设置10ms `statement_timeout`后执行`pg_sleep(0.05)`，经真实ProductTools/savepoint重试及序列化MCP，确认两次真实57014最终为`mcp_timeout`，后续工具额度已耗尽；`test_mcp_expired_query_deadline_is_timeout`使用明确过期的QueryDeadline走真实工具/MCP，也先观察到错误的`mcp_unavailable`后修正。`test_query_deadline_rejects_expired_session[apply/check]`断言专用超时类型；`test_mcp_unrelated_dependency_failures_remain_unavailable`覆盖普通不可用及真实42501/08006，错误文本含私人哨兵和timeout仍返回固定`mcp_unavailable`且不重试。

本次精确命令：`uv run --project backend python -I /tmp/shop-phase-a-tests.py backend/tests/test_customer_service_products.py backend/tests/test_customer_service_guards.py backend/tests/test_customer_service_consultations.py backend/tests/test_customer_service_model_transport.py backend/tests/test_customer_service_model_limits.py backend/tests/test_customer_service_model_budget.py -q`：112 passed、2 warnings、23.13s。两项警告仍为Starlette/httpx及Alembic配置弃用。helper仅向测试子进程传入127.0.0.1:55445/shop_test及reset开关；`git diff --check`通过。本次不重跑全套或浏览器，不启动服务器，不调用提供方、不部署、不写Issue。

限制：真实超时语句由测试在数据库读取边界注入，证明真实PostgreSQL取消→DBAPIError→现有重试→MCP分类，不冒称普通商品SELECT在真实负载下自然耗时超限。PostgreSQL57014表示query_canceled，数据库主动取消也归同一受控超时类别；无任意阻塞Python强制取消证明。仍仅本地in-process ASGI MCP、受控整句语法；外部MCP/真实提供方验证与C均未执行，累计真实调用0、金额0。

## Phase C 持久付费预算预留（2026-10-23，未真实调用）

C的前置计量已实现：迁移`0020_cs_paid_budget`创建单例`customer_service_paid_budget`，以数据库行（非进程/会话内存）累计终身`attempts_committed≤200`与`charged_fen≤2000`（人民币20元），会话、worker、重启均不重置；初始`state='disabled'`，迁移外无环境变量可放行。

`customer_service_spend_guard.py`的`SpendGuard`在发送前原子预留整笔最坏成本：先锁单例行再锁预留行；必须提供受信代码给出的冻结`PriceCard`（版本、provider、model、来源、批准、币种、输入/输出/缓存命中费率、整数汇率），首次预留写入卡片JSON与SHA-256；此后任何不同卡片一律拒绝。金额全程整数运算并按分向上取整，不经过浮点。预留同时提交一次`attempts_committed`；达到200或下一次预留将超过2000分时永久转为`stopped`（`attempt_cap`/`spend_cap`），不因会话新建或重启恢复。`claim_dispatch`以`dispatch_claimed_at`实现一次性发送许可，已领取的预留绝不重发。

结算只接受时限内、且不超过预留输入12000/输出1500的实际usage，按同一冻结卡片重算并退回未用金额，重复结算幂等；超时、已结束或结果不明的预留保留全额，迟到响应不退款。usage超过预留上界或卡片缺失/损坏时转为`blocked`并保持全额，后续准入关闭。演示初始化器只接受迁移生成的零用量单例行（`disabled`、200/0、2000/0、无卡片、无停止原因、无时间戳除创建时间），一旦存在`armed`/`stopped`、尝试数、已用金额、卡片摘要或停止原因即拒绝初始化，避免把已发生的真实调用洗掉。

验证：`uv run --project backend python -I /tmp/shop-phase-a-tests.py backend/tests/test_customer_service_spend_guard.py backend/tests/test_customer_service_demo.py -q`：42 passed、2 warnings、8.10s；新增11项预算测试（含并发仅一个预留成功、重启后仍累计、卡片冻结、不明结果全额、超界闩锁、向上取整）及7项初始化器基线测试。完整后端：`... backend/tests -q`：285 passed、1 skipped、2 warnings、57.73s，迁移`0019 -> 0020`在该隔离测试库应用。

限制：尚未接入任何已启用的真实发送路径，真实provider transport仍无条件关闭；`PriceCard`尚未填入经核实的官方价格与汇率，因此`reserve(price_card=None)`一律拒绝。费率按输入全量缓存未命中预留，缓存命中价仅记录不用于降低上限；输入上界来自既有12000/1500预留，未证明提供方实际计费token不超过该值。结算金额按首笔预留时冻结的同一卡片重算，是保守上界而非提供方发票核对，峰谷时段或实际缓存命中带来的低价不会追溯降低已记录金额。官方DeepSeek价格页与检索快照存在不一致且部分页面不可核验，故不把任何网络数字写死为生产价格。真实提供方请求累计仍为0、金额0；C真实验证须用户另行批准问题集、请求数与金额。

## 五条验收要求与证据

| 原始要求 | 核对结果 | 实现及验证证据 |
|---|---|---|
| 浏览器→客服后端→受控商品列表/详情；身份不可覆盖，禁止任意URL/SQL/管理员工具/通用透传 | 匿名确定性及演示买家路径通过；外部MCP及自由文本未完成 | customer_service_products.py仅分发两个具名工具，严格Schema拒绝额外字段；app.py及consultations共用匿名商品准入及认证演示白名单。test_product_tools_reject_unknown_tools_and_arguments覆盖execute_sql、user_id、url及identity；新增匿名API及真实桌面/移动Chrome覆盖商品事实、私有数据拒绝、跨会话页面、退出和绝对过期。此前演示部署的匿名401是旧镜像证据 |
| 名称/价格/可售库存/状态一致；未知、空结果、故障区分；不承诺补货 | 通过 | test_catalog_api.py覆盖事实、空列表、fixture变更及不可访问详情；e2e/customer-service.spec.ts分别验证三类提示。e2e/customer-service-demo.mjs比较全部4件fixture与普通详情API的名称/分类/精确价格/库存；普通详情仅返回已上架商品且不含is_listed，客服明确返回true。无补货预测逻辑 |
| 请求标识/时间/状态/裁剪数据；未知参数拒绝；不泄露堆栈或秘密 | 通过 | ProductTools统一envelope；API错误包装和no-store。test_catalog_api.py覆盖认证/权限/验证/限流/依赖及日志故障的受控响应；实际部署未知参数422，日志记录仅允许字段。商品描述不进入工具结果 |
| 只读临时故障至多一次重试，鉴权/权限/参数不重试 | 通过；故障注入证据来自shop_test，未在演示库重复注入 | test_read_retry_consumes_same_two_attempt_budget以真实PostgreSQL SQLSTATE故障验证40001/40P01/55P03/57014最多2次实际尝试，42501及08006不重试；严格参数拒绝在读取前。12项浏览器回归覆盖401/403/422/429不重试，503只有一次浏览器请求；messages POST不自动重放 |
| 首页入口/实际查询/手机布局；恶意商品文案不能改变权限或写操作；服务令牌不进入模型/日志/前端 | 通过于当前无提供方调用范围；首页证据来自项目页面测试，独立部署只挂载客服页 | e2e/customer-service.spec.ts覆盖首页及恶意商品文案按文本展示；真实Chrome→API→shop_test和已启动演示均覆盖查询/手机布局。model facts哨兵测试排除身份与不可信文案；服务端工具不提供写入口。演示未配置MCP/模型服务令牌，因此不宣称真实提供方令牌链路已验证。浏览器必要的CSRF及页面交接标识不属于MCP/模型服务令牌 |

## Phase A 匿名确定性读取验收（2026-10-23）

用户批准的A覆盖旧“仅演示买家”限制，规范源同步至运行契约、集中提案和演示配置。匿名身份仅由服务端会话生成；活动/CSRF/续期不延长自建立起30分钟绝对期限，退出撤销旧资格。跨会话页面及咨询拒绝；匿名订单、地址、购物车和管理员数据401，订单选择及额外身份/URL/SQL参数拒绝。GET/messages共用每会话20/60秒及连接IP60/60秒额度，创建新匿名会话或伪造转发头不能绕过IP额度。空结果、未知商品和故障提示沿用既有区分；政策归#4并明确不可用。

执行证据按来源区分：

- 中断前代理报告：通过`/tmp/shop-phase-a-tests.py`运行完整后端（`SHOP_RUN_BROWSER_TESTS=1`），246 passed，包含真实Chrome→API→隔离shop_test的匿名桌面/移动查询，以及日志字段白名单断言。helper仅向测试子进程传入127.0.0.1:55445/shop_test和reset开关；本次接续未重复完整套件。helper内部执行`uv run --project backend pytest`并转发调用方测试参数；接续上下文未保留该次完整命令、耗时及警告数，不补写推测值。
- 中断前代理报告：使用父工作区依赖执行`tsc -b && vite build`通过；本次接续未重复构建。
- 本次接续实跑：在本worktree使用父工作区可执行文件`/Users/leizhenyang/projects/shop/node_modules/.bin/playwright test e2e/customer-service.spec.ts`，12 passed，13.8秒。仅loopback临时Vite和模拟API，覆盖首页入口、列表/详情、恶意文案文本展示、错误区分、不自动重试、固定咨询/交接/续期及移动布局。测试后停止本worktree临时Vite。
- 已保存真实浏览器截图：`/tmp/shop-phase-a-desktop.png`、`/tmp/shop-phase-a-mobile.png`。截图展示匿名商品名称、价格129.00、可售库存24、上架状态和请求标识/UTC查询时间，不含秘密。临时文件保留供核查，不作为永久仓库附件。
- 后续独立复核发现商品GET新建CSRF会话可能与咨询POST并发轮换令牌；提交f13a47e以页面级sessionLane串行化CSRF获取和咨询POST完成，不自动重放POST。先以真实Chrome交错请求复现，再通过修复回归；全套模拟页面测试13 passed。

A真实模型调用0次、金额0；未变更订单或确认凭据契约，未修改开发/演示库、未部署。B随后已实现并记录于上文，不将A结果单独作为完整#3通过或关闭依据。

## 此前源码审查修复的验收边界

在已提交基线dc7c426之上，9bfd0ea修复启动日志过期清理、维护任务独立失败/重试、90秒交接hash清除和GET/咨询共用准入。临时目录隔离运行5项maintenance/admission纯测试通过。随后经用户明确授权，仅在127.0.0.1:55445/shop_test运行maintenance、admission、consultations、startup、guards及catalog API回归：74 passed、2项依赖弃用警告，15.63秒；包含新增3项PostgreSQL咨询测试和启动日志断言，0019迁移已在该测试库应用。重置开关仅传入测试子进程，不触及开发库或演示库。首次测试因缺少模块导入所需SHOP_DATABASE_URL在收集阶段退出；将它同样指向指定测试库后通过。前端构建、12项模拟API浏览器回归及合成部署静态预检亦通过（修复未改前端或部署配置）。现有运行演示镜像未重新构建或部署，下列233项及部署/恢复记录是此前基线证据；本次真实模型调用0次。

## 执行证据（修复前基线）

- 完整后端：233 passed、2 warnings，45.24秒。仅127.0.0.1:55445/shop_test，重置开关仅在获准测试子进程；SHOP_RUN_BROWSER_TESTS=1启用真实浏览器链路。警告为Starlette/httpx和Alembic配置弃用。
- 独立浏览器回归：12 passed，10.6秒，模拟API；不冒充真实后端验证。
- 演示实际部署：独立shop-customer-service-demo，三服务DB/API/Web，入口http://127.0.0.1:18011/customer-service.html。两买家、管理员及匿名边界、全部商品事实、列表/详情/咨询、移动布局、自由文本不发请求均通过。
- 实际文件日志：安全目录0700/UID10001、文件0600、允许字段、无正文哨兵；API/Web只读根及Docker logging=none，Nginx临时目录在tmpfs，PostgreSQL不收集文件日志/不记录语句。保留清理由日志边界测试验证，未等待7天实测。
- 恢复：独立新卷迁移/fixture初始化/启动7.454秒；到浏览器及旧会话/旧密码/旧咨询拒绝检查完成的总耗时上界124.32秒，小于1800秒目标。恢复副本已停止，卷保留；原演示运行，原卷未删除。运行期咨询/操作证据不恢复。
- 镜像/网络/日志证据详见[部署验收单](../deploy/customer-service-demo/acceptance.md)。外网连通探测被自动审批拒绝，只有API/DB连接internal网络的配置证据，不宣称做过外部连通实测。

## 剩余交付与限制

用户随后授权提交当前受控演示成果并更新GitHub #3，保持工单开启。提交仅包含客服交付范围，普通目录既有参数限制改动保留在工作区。工单更新记录验收证据与剩余缺口，不标记全部完成；具体提交标识以Git历史和工单交付评论为准。

保留：固定演示数据、匿名只读商品及两名演示买家、受控问题、无真实政策/订单客服、无外部商品MCP、无完整模型循环、无付费调用。未来扩展这些能力须补对应实现和验证，不能直接引用本报告当作完成证据。
