# 客服隔离演示部署差异

状态：用户已批准配置方案，本目录仅准备差异，未启动。关联[审核稿](../../docs/customer-service-demo-configuration-plan.md)。不得在缺少下述保护时启动商城API或模型分支。

## 文件与差异

- compose.yaml是独立配置，不与既有WeKnora或商城Compose叠加；固定项目名shop-customer-service-demo，无container_name或external卷/网络，不继承现有.env。
- WeKnora和数据库依赖采用本机现有镜像RepoDigest；固定revision来源见运行证据。digest固定不等于已验证镜像运行。
- .env.example仅变量模板，实际.env由仓库忽略；新建专用秘密，商城数据库密码使用至少32位URL安全字母数字以适配连接URL。不得复用现有数据库/JWT/MCP秘密。
- 数据库、文件和docreader临时卷均由新项目拥有；Redis使用内存状态，不恢复旧队列或授权。所有服务restart=no，网络internal，初期不允许外部模型/embedding出网。
- nginx-mcp.conf替换演示代理主配置，跳过原镜像模板entrypoint；仅/mcp/转发，关闭access日志、运行错误输出及上游重试，阶段超时各5秒。商城仍负责绝对deadline。原镜像日志及路由不继承。
- 默认候选入口127.0.0.1:18081（MCP）、127.0.0.1:18011（商城API）。初检18080被占用，故改18081；启动前必须重新检查。

## 明确未启用

商城API位于pending-demo-guards profile。现有镜像没有客服、演示账号白名单、受控问题、fixture哈希及模型输入映射；不能用虚构环境变量宣称已启用这些保护。模板要求后续提供审核过的API镜像，不默认使用当前镜像。

未提供Web商城入口或WeKnora管理UI，MCP代理拒绝其他路径；首次管理员、知识库、受限端点的初始化需单独设计本地流程，当前禁用注册。不复制现有数据库或创建真实政策。

DEMO_WEKNORA_CONFIG必须指向另行准备并审查的演示专用config.yaml，不直接挂载现有实例配置。缺文件禁止自动创建。该文件尚未生成：需核对固定镜像的配置字段、可选后端与密钥引用，避免带入现有模型凭据。internal网络会阻断外部模型/embedding，需在获准能力实现后准备受控出口，不把network internal当作模型已能工作。

安全结构日志writer、7天+最多1小时回收、fixture清单/种子导入、日志文件出口禁存及恢复演练尚未实现。logging none只阻止Docker stdout持久化，镜像内部文件与临时目录仍须哨兵检查；代理诊断丢失是明确取舍。不启用自动删除或备份。

## 已执行静态验证

Docker Compose v5.4.0使用纯合成密码和不存在的占位配置路径执行config --format json，内存解析后检查：项目名、7个服务、无全局container_name/继承env_file、所有发布端口仅127.0.0.1、所有网络internal、全部logging none、bind只读且create_host_path=false、API profile默认隔离。未输出解析后的环境或真实秘密。解析通过不检查bind源文件或镜像启动。

未运行up/run/build/pull/exec演示容器；未创建卷。Nginx配置仅静态审查，未在候选容器中执行nginx -t；需启动获准时先验证镜像入口、配置语法、DNS及健康检查，再开放入口。docreader健康检查命令与现有镜像运行配置一致，候选仍需独立验证。

## 后续实施顺序与回退

1. 先完成演示config.yaml、fixture及账号初始化方案；实施后续票的API保护、日志writer和共享计数，模型默认关闭。
2. 重新解析配置、检查digest/端口/卷，确认只会创建新项目资源。仅在获准启动后初始化新数据库，不调用shop_test重置或复制shop_dev。
3. 验证容器健康、MCP只读及限定库、错误分类、静态及实际超时/限流；失败保持入口关闭。不为测试停止既有Redis或WeKnora。
4. 以合成哨兵验证账号/输入/日志边界及隔离恢复，记录实际RTO。配置解析不能替代API/浏览器验收。
5. 回退只停止新项目服务，保留卷供检查，不使用down -v，不触及当前部署及旧日志。

本目录可供审查部署差异，尚不构成可直接上线的完整客服环境。#1仍需将批准的演示范围与后续验收责任收口，后续票负责产品实现。
