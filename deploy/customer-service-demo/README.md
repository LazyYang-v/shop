# 客服隔离演示部署差异

状态：用户已批准配置方案，本目录仅准备差异，未启动。关联[审核稿](../../docs/customer-service-demo-configuration-plan.md)。不得在缺少下述保护时启动商城API或模型分支。

> 2026-10-23 后续更新：主演示已按用户授权用合成政策镜像完成重启与容器内验收，详见[验收单](acceptance.md)及[合成政策实施记录](../../docs/customer-service-policy-implementation.md)。真实 WeKnora、真实商城政策及真实模型 exchange 仍关闭；下文“未启动/未生成/未初始化”等历史限制保留为最初审查记录，当前运行状态以验收单为准。

## 文件与差异

- compose.yaml是独立配置，不与既有WeKnora或商城Compose叠加；固定项目名shop-customer-service-demo，无container_name或external卷/网络，不继承现有.env。
- WeKnora和数据库依赖采用本机现有镜像RepoDigest；固定revision来源见运行证据。digest固定不等于已验证镜像运行。
- .env.example仅变量模板，实际.env由仓库忽略；新建专用秘密，商城数据库密码使用至少32位URL安全字母数字以适配连接URL。不得复用现有数据库/JWT/MCP秘密。
- 数据库、文件和docreader临时卷均由新项目拥有；Redis使用内存状态，不恢复旧队列或授权。所有服务restart=no，网络internal，初期不允许外部模型/embedding出网。
- nginx-mcp.conf替换演示代理主配置，跳过原镜像模板entrypoint；仅/mcp/转发，关闭access日志、运行错误输出及上游重试，阶段超时各5秒。商城仍负责绝对deadline。原镜像日志及路由不继承。
- 默认候选入口127.0.0.1:18081（MCP）、127.0.0.1:18011（商城API）。初检18080被占用，故改18081；启动前必须重新检查。

## 明确未启用

所有基础服务位于pending-demo-gates profile，默认没有可启动服务；商城API单独位于pending-demo-guards profile，基础profile不会启用API。显式指定服务也可能激活profile，profile不是授权或运行保护，不能在运行门槛未满足时启动。本候选已接线源码实际读取的SHOP_CUSTOMER_SERVICE_DEMO_MODE、FIXTURE_PATH、FIXTURE_SHA256、BUYER_IDS、LOG_DIRECTORY以及SHOP_REGISTRATION_ENABLED；仍须构建并审核包含对应代码的新API镜像，不默认使用当前镜像。源码与Compose接线不代表已验证镜像行为。API显式使用--no-proxy-headers和--no-access-log。

未提供Web商城入口或WeKnora管理UI，MCP代理拒绝其他路径；首次管理员、知识库、受限端点的初始化需单独设计本地流程，当前禁用注册。不复制现有数据库或创建真实政策；合成政策仅来自本目录受hash约束的fixture，不写入WeKnora。

DEMO_WEKNORA_CONFIG必须指向另行准备并审查的演示专用config.yaml，不直接挂载现有实例配置。缺文件禁止自动创建。该文件尚未生成：需核对固定镜像的配置字段、可选后端与密钥引用，避免带入现有模型凭据。internal网络会阻断外部模型/embedding，需在获准能力实现后准备受控出口，不把network internal当作模型已能工作。

安全结构日志writer及回收已有源码，Compose新增仅本项目拥有的customer-service-logs卷；必须在API首次启动前另行获准准备目录owner/0700并以镜像运行UID验证writer.verify()，普通新卷默认权限不能视为合格。fixture及显式初始化入口见下节。日志文件出口禁存、实际到期回收上界及恢复演练尚未运行验证。logging none只阻止Docker stdout持久化，镜像内部文件与临时目录仍须哨兵检查；代理诊断丢失是明确取舍。本次未运行删除任务或备份。

## 版本化fixture与显式初始化（未执行）

products.v1.json包含4个虚构商品，使用API启动check_fixture的精确字段格式；文件原始字节SHA256为b730b65266d096918f8f5e085c960ed5acccf6378b3b1e222bfa379141169b1b。修改任何字节必须同步审核代码/Compose中的digest。首商品是现有0002迁移的虚构针织开衫；其余三个明确标注演示，零库存商品用于边界检查。不创建订单、地址、会话或政策，不复制开发库。

policies.synthetic.v1.json只包含**标注为“虚构演示政策（非真实商城政策）”的合成规则**，不是真实商城政策。文件原始字节SHA256为79a224ffd33037578402a706095e063cb80d4a0498fe0a77d6f049409ab83163。它提供合成权威登记（policy_id、source、version、生效区间、状态、KB+文档标识和规范正文哈希）及进程内检索索引替身；索引残留、旧版本、未来版本、已删除残留和研究资料用于验证拒绝路径。启动时校验文件hash、合成标签、`synthetic://`来源、规范正文哈希和发布区间冲突；检索只按KB+文档ID映射回登记。**不连接、不写入当前共享WeKnora，不包含端点/令牌，真实政策答复路径保持关闭。** 修改文件必须同步Compose、预检和验收记录。

固定身份如下；只有前两项进入客服白名单。

| 角色 | UUID | 邮箱 |
|---|---|---|
| 买家1 | de100000-0000-4000-8000-000000000001 | buyer-one@customer-service.example |
| 买家2 | de100000-0000-4000-8000-000000000002 | buyer-two@customer-service.example |
| 管理员 | de100000-0000-4000-8000-000000000003 | admin@customer-service.example |

初始化命令入口为shop-api initialize-customer-service-demo --fixture <绝对fixture路径> --fixture-sha256 <上述digest> --secrets-file <仓库外私有JSON绝对路径>。这只是待执行说明，本次未初始化数据库。数据库URL只从SHOP_DATABASE_URL取得；仅接受postgresql或postgresql+psycopg、库名shop_customer_service_demo、主机shop-db/localhost/127.0.0.1/::1，拒绝所有URL查询选项并在事务内核对current_database()。不得指向shop_dev、现有部署或其他主机。

JSON的三个键必须精确为上表邮箱，值为外部生成的不同12–128字符密码；不在仓库、命令行参数、输出或环境模板中放密码。文件必须由执行用户拥有、为普通文件、无组/其他用户权限（0600）、不是符号链接，存于仓库外。Python调用initialize_customer_service_demo可直接接收内存passwords字典。数据库仅保存Argon2哈希。CLI失败统一输出受控信息，不输出底层数据库异常或秘密。

先准备已审核的数据库结构；迁移时不设置SHOP_ADMIN_EMAIL或SHOP_ADMIN_PASSWORD_HASH，避免0004写入额外管理员。默认初始化要求所有public应用表为空，仅alembic_version可有迁移记录。普通alembic升级会由0002插入一条商品：仅在审核确认这是全新迁移基线时显式加--allow-migration-seed；该选项仅额外容许0017迁移固定单例customer_service_model_guard的精确一行{id: 1, metering_blocked: false}且保留不变，其余应用表为空；任何使用计数/预约或blocked单例都拒绝。并逐字段检查唯一商品（含描述、图片、价格、库存、上架标记、created_at非空且listed_at等于created_at），fixture必须含相同商品。运行时生成的时间戳不固定到提交日期，其余字段完全固定。原行保持不变，不更新、不删除；不合格即拒绝。不要通过清理已有库来满足条件。

初始化在单一事务中锁定所有应用表，再检查空表/基线、创建三个身份及缺少的fixture商品，flush后通过实际check_fixture重新核对文件hash和数据库行，成功才commit。失败回滚全部新增，第二次调用拒绝；这不是覆盖、重置或自动恢复命令。并发初始化被表锁串行化。恢复需单独获准的新空卷及新秘密，不删除旧卷。

测试位于backend/tests/test_customer_service_demo.py，通过公开初始化边界验证创建、重复拒绝、未知表已有行拒绝、严格基线复用、变更基线拒绝、hash拒绝、事务回滚、危险目标拒绝及私有秘密文件。生产入口永不接受shop_test；专用测试入口额外调用现有validate_test_database_url（SHOP_ALLOW_TEST_DATABASE_RESET=1）并要求随机demo_initializer_test_<32位hex>隔离schema。测试不清理public业务数据，但现有全局conftest仍会迁移/重置shop_test；必须由父会话协调授权后运行，例如从仓库根目录backend/.venv/bin/pytest backend/tests/test_customer_service_demo.py。2026-10-23已获用户明确授权并完成包含本组的全后端回归：233 passed、2项依赖弃用警告，45.24秒；启用真实浏览器测试，所有数据库操作仅在shop_test内，开关仅传入测试子进程。此结果不代表实际演示部署已初始化。

## 已执行静态验证

可从仓库根目录重复执行`python3 -I deploy/customer-service-demo/preflight.py`。脚本只使用合成环境及`--env-file /dev/null`解析Compose，不读取仓库秘密、不启动服务、不创建卷；核验默认0服务、profile、loopback、内部网络、日志驱动、只读挂载、fixture哈希及买家白名单。该预检已通过，不代表容器运行验收。

Docker Compose v5.4.0使用纯合成密码和不存在的占位配置路径执行config --format json，内存解析后检查：项目名、7个服务、无全局container_name/继承env_file、所有发布端口仅127.0.0.1、所有网络internal、全部logging none、bind只读且create_host_path=false、全部服务profile默认隔离（默认0服务，基础profile不含API）。未输出解析后的环境或真实秘密。解析通过不检查bind源文件或镜像启动。

本次修改后再次以纯合成秘密、/dev/null env文件及不存在的占位WeKnora配置执行Compose config --format json，输出仅在内存解析：确认注册关闭、两个Uvicorn日志/代理参数、fixture只读挂载及独立日志卷、所有profile仍opt-in、全部logging none和internal网络。静态检查另含Python AST语法、fixture JSON/商品数/hash及git diff --check；数据库回归结果见上文233项通过记录。未运行up/run/build/pull/exec演示容器；未创建卷。Nginx配置仅静态审查，未在候选容器中执行nginx -t；需启动获准时先验证镜像入口、配置语法、DNS及健康检查，再开放入口。docreader健康检查命令与现有镜像运行配置一致，候选仍需独立验证。

## 后续实施顺序与回退

1. 审核本次fixture、初始化器、API保护及共享计数代码并完成父会话协调的测试；另行完成演示config.yaml，模型保持关闭，真实政策/WeKnora入口保持未配置，只有受hash约束的合成政策fixture可被加载。
2. 重新解析配置、检查digest/端口/卷，确认只会创建新项目资源。仅在获准启动后初始化新数据库，不调用shop_test重置或复制shop_dev。
3. 验证容器健康、MCP只读及限定库、错误分类、静态及实际超时/限流；失败保持入口关闭。不为测试停止既有Redis或WeKnora。
4. 以合成哨兵验证账号/输入/日志边界及隔离恢复，记录实际RTO。配置解析不能替代API/浏览器验收。
5. 回退只停止新项目服务，保留卷供检查，不使用down -v，不触及当前部署及旧日志。

本目录可供审查部署差异，尚不构成可直接上线的完整客服环境。#1最终验收及后续票责任已收口于[运行契约](../../docs/customer-service-runtime-contract.md)；建议关闭核实票不代表本候选可以启动。
