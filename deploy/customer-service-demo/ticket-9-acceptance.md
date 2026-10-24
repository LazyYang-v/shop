# 客服 #9 部署与隔离恢复验收

日期：2026-10-24。源码归档 `4e43485be99ddf1a103c21165cef481d99b5b338`，产品代码与通过完整 399 项后端回归的 `a4478a6` 相同。使用 `run` 技能启动实际应用并驱动真实 Chrome；不是将测试库通过视为已部署。

## 镜像与资源范围

| 项目 | 实际值 |
|---|---|
| 本地 API 标签 | `shop-customer-service-demo-api:20261024-ticket-9-4e43485` |
| API 镜像 ID | `sha256:d3e04062388ae0433e5f938423890762bc47ba3c36612cab198262a0105c4d02` |
| OCI revision | `4e43485be99ddf1a103c21165cef481d99b5b338` |
| 主演示 | 项目 `shop-customer-service-demo`；[客服页面](http://127.0.0.1:18011/customer-service.html) |
| 恢复副本 | 项目 `shop-customer-service-demo-recovery-ticket-9-20261024`；loopback `18013`；新数据库和日志卷，验收后停止服务、保留卷 |
| 数据库 | 两项目各自的 `shop_customer_service_demo`，账号 `shop_demo`，无宿主机发布端口；未访问开发库或共享 WeKnora |
| 主演示升级 | `2026-10-24T06:10:48Z` 开始，3.440 秒完成迁移检查、API/Web 重建、健康与页面哈希核对；原数据库卷保留 |
| 旧 API 镜像 | `sha256:0a4547ae43c02f4d808d7bf8dab1c6bf06ceba6776dc946c7341d02184a290c6` 保留，未删除 |

镜像从 `git archive 4e43485` 构建，未发送工作区的忽略文件作为构建上下文；依赖由现有 Dockerfile 的版本范围解析，最终镜像 ID 是本次运行的准确标识，不承诺再次构建得到相同字节。主部署使用 [compose.products.yaml](compose.products.yaml)，API/Web 只读根目录、UID10001、内存临时目录和 Docker `logging=none`；API/数据库只在 internal 网络，Web 仅 loopback 发布。

用户明确授权了主演示迁移检查及 API/Web 强制重建、通过商城 API 创建虚构验收订单、新恢复卷和仓库外私有凭据。默认地址池耗尽后，又单独批准恢复 ingress 使用 `10.203.9.0/28`；已核对与现有 Docker 子网和宿主路由不冲突，仅 [恢复覆盖配置](compose.recovery-ticket-9.yaml)采用该网段，未删除或修改其他项目网络。临时政策不可用及重启/恢复也取得单独授权。

## 实际浏览器与 API 证据

执行入口：[e2e/customer-service-deployment.mjs](../../e2e/customer-service-deployment.mjs)。桌面 `1440×1000`、移动 `390×844`，分别使用两个专用买家。该脚本的 `assertions` 只计请求检查，不是测试场景总数。

| 模式 | 实际结果 | 结束时间 UTC |
|---|---|---|
| deployment | 两端通过；44 次计数检查，浏览器 pageerror 0 | `2026-10-24T06:15:27.504Z` |
| recovery | 两端通过；10 次计数检查，浏览器 pageerror 0 | `2026-10-24T06:20:00.412Z` |
| outage | 两端通过；8 次计数检查，浏览器 pageerror 0；随后恢复正常政策 | `2026-10-24T06:26:14.285Z` |

验收通过商城登录、地址、购物车、下单、模拟支付、管理员发货和库存接口创建 1 件**不在客服商品白名单内**的虚构验收商品及每买家各 1 笔待收货、1 笔待支付订单。全部原 fixture 的名称、金额、库存和上架状态保持一致，没有通过数据库改库存来绕过 fixture 检查；后续取消库存仍由原业务事务恢复。

每端实际完成：

1. 商品事实与四件批准 fixture 一致，合成政策引用为发货 v2；匿名查订单 401、管理员客服查询 403、私人未知文本澄清。
2. 订单先列表、后本人点击选择；待收货单两种物流/退款表述分别通过，展示虚构已保存运单并说明没有实时轨迹、预计送达、退款接口，不签发不适用方案。
3. 已选订单与发货政策组合返回各项来源和时间；政策来自合成规范登记。
4. 选择待支付单并提出方案，订单仍待支付；点击确认后真实提交成功，浏览器丢失响应，仅核验而不重发。证据与独立订单 API 一致，库存恰增加 1，重复核验证据相同，终态文案替换旧未知说明。
5. 另一买家不能读取订单或核验操作；确认凭据不进 DOM/storage，页面不出现地址电话、没有横向溢出。已实际查看两端截图。
6. 临时 [policy-unavailable 覆盖配置](compose.policy-unavailable.yaml)将合成政策路径及哈希置空，只重建主演示 API；组合返回 `partial/policy_unavailable` 并保留本人订单，固定查单仍成功。随后在 `finally` 中用基础配置重建 API，独立公共请求再次验证正常发货 v2。此故障证明部署的能力不可用处理，不证明真实 WeKnora 断连或取消传播。

持久演示采用默认确定性路径，无合成模型构造器注入；测试库中的合成六工具循环证据继续单列。三种模式真实模型请求、WeKnora 请求及付费调用均为 **0**。

## 恢复计时与边界

开始 `2026-10-24T06:12:02.142971Z`，结束 `2026-10-24T06:20:00.412Z`，总耗时 **478.269 秒**，包含 Docker 默认地址池耗尽、诊断和用户确认等待，达到 1800 秒目标。没有剔除失败时间重新计时。

在新卷迁移并以新密码初始化相同固定身份/四件商品后，真实两端浏览器验证：旧会话 401、旧密码 401、已登录新身份使用旧咨询 410；新密码登录、商品与合成政策查询成功。新库订单/取消操作均为 0，旧订单读取 404。这证明 fixture 重建及旧资格失效；运行期订单、聊天及操作证据没有备份或恢复，**RPO 无保证**，也不是生产恢复 SLA。

## 日志、秘密与证据位置

最终抽查主演示 121 条安全记录，含六工具；恢复 6 条记录，含商品及政策。所有记录精确为 `request_id/tool/error/duration_ms/count/recorded_at`；用户输入哨兵、地址电话、买家邮箱及验收运单 0 命中。目录0700、JSONL0600；API环境无模型/WeKnora令牌或密钥。主/恢复 API 均无外部模型 transport，只有受控进程内合成政策索引。未以 `logging=none` 单独推断完整保留契约通过。

本轮私有目录在仓库外，目录0700、凭据/会话文件0600；此处只记录定位，不包含秘密：

- `/private/tmp/shop-customer-service-ticket-9-deploy-20261024`：升级记录、虚构订单引用、供恢复负向检查的旧会话、部署及故障模式结果、桌面/移动截图。
- `/private/tmp/shop-customer-service-ticket-9-recovery-20261024`：新恢复私有凭据、启动/恢复结果及两端截图。

这些临时文件不是长期归档；本文件保存脱敏的持久结果，脚本保存复现接口。浏览器入口示例需填写本地受控文件路径，不能粘贴密码：

```sh
SHOP_DEMO_ORIGIN=http://127.0.0.1:18011 \
SHOP_DEMO_ACCEPTANCE_MODE=deployment \
SHOP_DEMO_PASSWORD_FILE='<仓库外0600密码JSON>' \
SHOP_DEMO_ARTIFACT_DIRECTORY='<本次新建的仓库外0700目录>' \
node e2e/customer-service-deployment.mjs
```

该模式会创建虚构数据并执行两次取消；重跑前须确认同一隔离演示范围，不指向开发或真实商城。`recovery` 模式另需 `SHOP_DEMO_PREVIOUS_SESSION_FILE`、`SHOP_DEMO_PREVIOUS_PASSWORD_FILE`，指向同次升级产生的私有旧身份资料。`outage` 模式另需 `SHOP_DEMO_PREPARED_ORDERS_FILE`，且必须先明确授权临时覆盖及恢复，不因配置存在就执行。

部署使用仓库中的准确源码归档构建，命令从仓库根目录执行：

```sh
git archive 4e43485 | docker build \
  --label org.opencontainers.image.revision=4e43485be99ddf1a103c21165cef481d99b5b338 \
  -f deploy/customer-service-demo/Dockerfile \
  -t shop-customer-service-demo-api:20261024-ticket-9-4e43485 -
```

Compose 必需变量为 `DEMO_SHOP_DB_PASSWORD`、`DEMO_SHOP_API_IMAGE`（构建后的准确 ID）、`DEMO_SHOP_PORT`；只从私有文件读入子进程环境，禁用隐式 `.env`，不输出环境值。主演示已是迁移0021，先用 `--entrypoint alembic shop-api upgrade head` 检查，再仅重建 API/Web；保留数据库/日志卷。本次原卷升级和新卷恢复的具体操作脚本保存在会话外部上下文中，私有凭据不会随源码发布。

恢复使用 `compose.products.yaml` 叠加 `compose.recovery-ticket-9.yaml`，新项目、端口18013和新卷；通过 [README 初始化流程](README.md#版本化fixture与显式初始化未执行)迁移、初始化、预置日志0700，再启动 API/Web。若资源已经存在，先检查而不是重复初始化或删卷；本次恢复资源保留，需要新一轮演练时另定新的项目/子网范围。当前演练结束以 `docker stop` 只停止本次三个恢复容器，未删除卷。

## 尚未完成的真实门槛

用户已确认真实政策及账号适用的外部保留资料尚未准备。[真实放行资料清单](../../docs/customer-service-real-release-prerequisites.md)把用户材料与工程验证分开；专用 WeKnora/真实提供方兼容性、真实政策质量、故障和保留契约仍未验。#9 的合成部署与 R09 已有当前版本证据，真实首版继续阻塞，工单保持 OPEN。
