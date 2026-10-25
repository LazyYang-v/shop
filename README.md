# 单商家商城作品集

后端已覆盖首版商城闭环：商品与库存管理、购物车和地址、结算与模拟支付、取消及超时关闭、订单查询、管理员发货和买家确认收货。前端提供商品发现、主题频道、个人中心、地址簿、购物车、地址选择/新增、下单后跳转我的订单、模拟支付/取消/确认收货和物流详情，并已接入管理员商品、库存与订单发货页面。帮助中心、公告和分类导航提供完整访问入口；整站真实数据库发货到收货的完整验收仍待完成。

## 客服演示与验收

客服已按用户批准的[13 项作品集发布门槛](docs/customer-service-portfolio-release.md)完成验收，**已验收功能候选固定为 [`941fe4e`](https://github.com/LazyYang-v/shop/tree/941fe4e61c3e725db230f5139adb1a4a3a3661c3)**。源码仓库 [LazyYang-v/shop](https://github.com/LazyYang-v/shop) 当前公开；该结论只覆盖候选版本的虚构商品、专用买家和明确标注的合成政策，以及当时记录的权限、确认与结果核验，不接真实买家数据。真实商城政策、真实 WeKnora 产品入口与持久演示的外部模型调用保持关闭。

组合咨询、桌面/移动复现及 32 个固定场景见[客服最终评测](docs/customer-service-final-acceptance.md)，默认参数见[运行契约](docs/customer-service-runtime-contract.md)。`a4478a6` 完整回归为 399 项后端、28 项页面通过，六工具模型循环使用合成 exchange；`4e43485` 镜像的[隔离部署与 478.269 秒恢复](deploy/customer-service-demo/ticket-9-acceptance.md)采用确定性组合，本机入口为 http://127.0.0.1:18011/customer-service.html。这些 #9 验收新增真实模型/WeKnora 调用均为 0；[#3 历史兼容性](docs/customer-service-issue-3-acceptance.md#c-真实调用与重试验收2026-10-23)在 `722ed62` 单独记录 6 次真实模型请求（2 次诊断失败、4 次成功），不等于当前六工具真实兼容性。WeKnora 的历史证据与合成补偿见[能力矩阵](docs/customer-service-weknora-acceptance.md)。

本次结论为“客服作品集发布验收通过”。[生产化前置条件](docs/customer-service-real-release-prerequisites.md)已归档，不阻塞作品集，也不表示真实商城上线、供应商零保留或账号级承诺已得到证明。

### 验收候选与后续开发

默认分支在 `941fe4e` 之后加入了六职责客服平台、FAQ/商品知识、商品对比与尺码建议、服务申请和人工工单、三栏工作台及配套测试（截至 `d382858`）。这些是**开发中能力**，不在 #9 的 13 项作品集发布验收或其 32 个固定场景内；下文“本机启动”介绍的是当前开发分支的用法，不能据此将旧候选的 399/28 项结果或隔离部署恢复结论套用到新功能。[改造记录](docs/customer-service-agent-redesign.md)保存新增测试与实际运行范围，[下一阶段整改规格](docs/superpowers/specs/2026-10-25-customer-service-agent-remediation-design.md)以 `b69f339` 为审计基线；若要把当前默认分支作为新的作品集候选，需针对准确提交重新完成并记录验收。

## 前置条件

- Python 3.12 或更新版本
- `uv`
- Node.js 20 或更新版本
- Docker Desktop / Docker Engine 与 Compose

## 本机启动

1. 创建本机环境文件并设置仅供本地开发的数据库密码：

   ```sh
   cp .env.example .env
   ```

   编辑 `.env` 中的 `SHOP_DB_PASSWORD`，不要提交 `.env`。

2. 启动专属开发 PostgreSQL 并构建 API 镜像：

   ```sh
   docker compose up -d db
   docker compose build api
   ```

3. 在开发数据库应用迁移：

   ```sh
   docker compose run --rm api alembic -c /app/alembic.ini upgrade head
   docker compose up -d api
   ```

4. 启动前端：

   ```sh
   npm install
   npm run dev
   ```

   打开 Vite 输出的本机地址。Vite 将 `/api` 请求代理到 `http://127.0.0.1:8011`。

   本机 Compose 启用商城集成客服，入口为 `/customer-service.html`，沿用商城账号登录态。后端代码或 Compose 环境变化后，须重新构建 API、应用迁移并启动 API；只刷新前端不会更新容器中的后端：

   ```sh
   docker compose build api
   docker compose run --rm --no-deps api alembic -c /app/alembic.ini upgrade head
   docker compose up -d --no-deps api
   curl http://127.0.0.1:8011/api/customer-service/mode
   ```

   模式检查应返回 `{"mode":"integrated","enabled":true}`。**以下集成客服功能属于当前开发分支，尚未纳入 #9 验收。** 集成客服支持有效 FAQ 优先答复、商城在售商品与知识条目问答、商品对比、推荐条件续接、分轮补充尺寸的尺码建议、本人订单与已保存物流查询、待支付订单确认取消，以及催发货、修改收货地址、发票、退换货/退款、少件/破损/错发、质保、补发、补偿等服务申请登记与人工工单。客服页会展示“常见问题”推荐（仅来自当前有效 FAQ 条目）和按本人订单状态的场景快捷入口（待支付/待发货/待收货）；点击“选择订单发给客服”可在聊天内查看本人订单候选并选单，订单列表和详情页的“联系客服”也可直接带入该订单，未登录时登录后继续。转人工受理后主动提供满意度评价入口。选定本人订单后可询问“退款进度”“补发进度”“发票开好了没”，只查询现有申请，不重复创建；工单审结不表示退款到账、补发完成或发票开具。申请由管理员在管理后台“客服工作台”审核，其中修改收货地址仅在审结并重验快照后应用，并保留执行证据。

   客服页采用“智能客服”三栏工作台：左侧服务导航、最近咨询和转人工，中间聊天与多行输入，右侧本人订单、当前商品/订单和常用售后；窄屏将两侧收为抽屉。右侧订单的“发送给智能客服”直接在当前聊天明确选单，商品、订单和已保存物流以业务卡片展示。按 Enter 发送、Shift + Enter 换行，查询时显示等待状态，收到回复后逐句渐显。最近咨询从服务端读取短期脱敏记录，刷新后可重新查看；浏览器只保留咨询索引，记录为只读，过期后明确提示，不自动重发旧消息或操作。返回商城保留进入客服前的分类、搜索词和分页 URL。

   P3 体验精修将推荐偏好、服务通知、工单列表、交接内容及申请表单放入独立面板，避免冲散聊天。商品列表横向展示并在同轮去重，再次查询同一商品时折叠旧卡片；订单默认显示尾号，完整信息按需展开，选单后右侧收起候选列表，只保留业务上下文。人工状态区分正在申请、等待接手、人工已接手和处理结束；接手以工单分配结果为准，人工模式下输入发送为该工单的留言，不承诺实时在线。返回智能客服不撤销原工单。补充或共享的响应不明时先查询核对，不自动重发；同一服务申请关闭再打开仍保留原内容与幂等请求编号。

   尺码建议只使用管理员发布的有效商品资料，例如结构化属性 `{"material":"棉","size_chart":{"M":{"height_cm":[160,170],"weight_kg":[50,60]}}}`；尺码范围必须为带单位含义的上下限数组。买家可分轮提供“身高168厘米”“体重110斤”，页面也提供尺寸填写表单；没有单位的数字不会被猜测，测量值仅用于本次咨询。肤质/肤色推荐只采信已发布的 `skin_types` / `skin_tones` 适用属性，价格和库存以商品目录为准。

   实际退款打款、开票、补发、真实承运商轨迹和外部平台（淘宝/京东/抖音/拼多多）接入尚未接通。六职责当前由确定性路由和受控流程执行，真实付费模型默认关闭。实现与验证见[改造记录](docs/customer-service-agent-redesign.md)，设计依据见[20 份公开资料研究](docs/customer-service-agent-reference-study.md)；小红书笔记未取得可核对全文，未计入这 20 份。隔离作品集仍使用独立 `18011` 环境；仅需从 Vite 跳转到它时才显式设置 `SHOP_CUSTOMER_SERVICE_MODE=demo` 和 `SHOP_CUSTOMER_SERVICE_ORIGIN`。

5. 健康检查与商品接口：

   ```sh
   curl http://127.0.0.1:8011/api/health
   curl http://127.0.0.1:8011/api/products
   ```

停止本地服务：`docker compose down`。删除开发数据卷是破坏性操作，慎用 `docker compose down -v`。

## 身份与本机结算演示账号

买家可在商城注册并使用邮箱登录。请使用虚构邮箱和演示专用密码，不要填写真实账号密码。首版不提供邮箱/短信验证或找回密码。邮箱去除首尾空白并转小写后唯一。

本机 `shop_dev` 已预置一个专用买家账号，可直接体验购物车、地址选择、结算和模拟支付：

- 邮箱：`checkout-demo@example.com`
- 密码：`DemoBuyer-_HfHrETK8WGTQQ`
- 默认地址：林女士，浙江省杭州市西湖区文三路 1 号
- 其他测试地址：浙江省杭州市拱墅区湖墅南路 88 号；上海市徐汇区漕溪北路 18 号

以上均为虚构演示资料，只存在本机 `shop_dev`。结算页默认选中默认地址，支持切换其他地址或创建新地址，新地址保存后自动选中。下单成功跳转到“我的订单”，可查看已购商品、订单详情、模拟支付、取消和物流信息。请勿用于真实配送。

新注册账号没有收货地址。管理员可设置 `SHOP_DATABASE_URL` 指向本机 `shop_dev` 后执行 `uv run --project backend shop-api prepare-demo-addresses`，为当前没有任何地址的活跃买家补充一个虚构默认地址；命令保留已有地址且可重复执行，拒绝其他数据库。此命令只准备当前账号，后续新注册的账号需要再次执行。

认证会话自登录起固定 7 天，匿名 CSRF 会话固定 30 分钟，均不滑动续期。获取 Token：`GET /api/auth/csrf`；所有状态变更请求携带 `X-CSRF-Token`，并校验同源 `Origin`。匿名会话过期后重新获取 Token 并由用户再次提交；请求不会自动重放。

本机创建管理员：先设置 `SHOP_DATABASE_URL` 指向本项目 `shop_dev`，运行 `uv run --project backend shop-api create-admin --email <虚构管理员邮箱>`，然后在交互提示中输入专用演示密码。密码不会写入源码或 shell 历史。也可将 `SHOP_ADMIN_EMAIL` 和 `SHOP_ADMIN_PASSWORD` 保存在被 Git 忽略的本机 `.env` 中，再执行 `set -a; source .env; set +a` 后用 CLI 建立/更新管理员；不要把 `.env` 分享或提交。公开注册只能创建买家。

清理过期会话可重复执行：设置 `SHOP_DATABASE_URL` 为目标数据库后运行 `uv run --project backend shop-api cleanup-expired-sessions`。命令仅删除 `expires_at` 已到期的匿名和认证会话；有效会话不受影响。会话有效性仍由每次 API 请求即时校验。

## 测试数据库安全

测试数据库必须单独启动，数据库名称必须精确为 `shop_test`，使用独立端口和独立 Docker volume。测试清理只有设置 `SHOP_ALLOW_TEST_DATABASE_RESET=1` 才可运行。不得把 `shop_dev` 或演示数据库配置给测试。

```sh
export SHOP_TEST_DATABASE_URL='postgresql+psycopg://shop:<password>@127.0.0.1:<test-port>/shop_test'
SHOP_DATABASE_URL="$SHOP_TEST_DATABASE_URL" \
  SHOP_ALLOW_TEST_DATABASE_RESET=1 \
  uv run --project backend pytest backend/tests -q
```

应用导入与测试夹具分别读取 `SHOP_DATABASE_URL`、`SHOP_TEST_DATABASE_URL`，两者必须指向同一隔离 `shop_test`；清理开关仅设置在本次测试进程，不写入 `.env` 或其他持久配置。

测试数据库容器与数据卷须在确认 `docker compose config` 解析结果和目标库名后单独创建。项目不会自动删除任何数据库卷。

## 阶段验收与首版剩余内容

- 第 1 阶段：商品目录从 PostgreSQL 提供给 React 商城页面。
- 第 2 阶段：买家注册/登录/退出、服务端会话、CSRF 和管理员访问保护。
- 第 3 阶段：商品详情、持久购物车、地址簿、结算订单快照、事务扣库存与幂等请求。
- 第 4 阶段：后端商品搜索/分类筛选/排序/分页与商品详情，购物车 UI 和模拟支付。开发库可通过 `uv run --project backend shop-api seed-demo-products` 幂等补充各首页分类的虚构演示商品；种子商品会写入带原因的初始入库审计记录并直接可售，而经管理员接口新建的商品仍默认库存为零，须经审计接口入库后才能购买。
- 后端补齐：买家订单分页与状态筛选、完整订单详情、取消未支付订单及一次性库存恢复、启动补扫与每分钟超时关闭、管理员订单查询/发货、买家确认收货、管理员商品维护及库存调整审计。
- 买家页面补齐：`?view=cart` 进入购物车，结算支持地址选择和新增；`?view=orders` 进入我的订单，订单详情及物流页面可按 URL 刷新恢复。物流仅展示保存的快递公司、运单号、发货及确认收货时间，没有接入外部快递轨迹。独立 HTML 设计稿：`/logistics-preview.html`。
- 前端补页：`?view=account` 个人中心、`?view=addresses` 地址簿（新增、编辑、删除、默认地址）、`?view=channel&channel=living` 等六个商品频道、`?view=help` 帮助中心、`?view=notices` 公告列表/详情、`?view=directory` 分类与网站导航、`?view=mobile` 手机使用说明。频道使用真实在售商品，不提供虚构优惠、直播或拍卖。原收藏夹入口调整为收货地址入口。
- 管理后台：管理员登录后进入 `?view=admin`，支持商品搜索/编辑/上下架/新建、库存调整与审计、订单查询及发货；普通买家无权访问，后端逐请求校验权限。
- 浏览器验证：`npx playwright test e2e/pages.spec.ts` 覆盖新页面导航、响应式、订单筛选恢复及地址/管理员操作。写操作使用模拟 API 验证请求及页面反馈，不修改开发数据库；频道商品使用实际 API。尚待真实数据库中覆盖发货到收货的完整验收，页面完成不代表整站首版验收通过。

## 新增后端接口

交互式接口文档：API 服务的 `/docs`，完整 schema 在 `/openapi.json`。私有接口要求认证会话；写操作同时要求当前 `X-CSRF-Token` 和同源 `Origin`。

| 能力 | 接口 |
|---|---|
| 本人订单分页与状态筛选 | `GET /api/orders?status=pending_payment&page=1&page_size=20` |
| 本人订单详情 | `GET /api/orders/{id}` |
| 取消待支付订单 / 确认收货 | `POST /api/orders/{id}/cancel`、`POST /api/orders/{id}/confirm-receipt` |
| 管理员订单列表 / 详情 | `GET /api/admin/orders`、`GET /api/admin/orders/{id}` |
| 管理员发货 | `POST /api/admin/orders/{id}/ship`，JSON 包含 `shipping_company`、`tracking_number` |
| 管理员商品列表 / 新建 | `GET /api/admin/products`、`POST /api/admin/products` |
| 管理员商品详情 / 编辑与上下架 | `GET /api/admin/products/{id}`、`PATCH /api/admin/products/{id}` |
| 管理员库存审计查询 / 调整 | `GET /api/admin/products/{id}/inventory-adjustments`、`POST` 同路径，JSON 包含 `delta`、`reason` |

商品创建库存为零，后续只能通过带原因的库存调整更改；普通商品编辑不接受 `stock`，商品不提供物理删除。订单详情包含商品/地址快照、各状态时间、关闭原因和物流信息。重复支付、取消、发货和确认收货返回 `409`，不会重复修改库存或覆盖物流信息。

订单创建使用买家范围内的 `Idempotency-Key`，重试同一次结算必须重用键；同一买家的购物车修改与结算在事务内串行化。订单关闭不恢复购物车。到期订单即时禁止支付，启动补扫及每 60 秒扫描负责关闭和恢复库存；扫描出错会记录日志，并在下一轮重试。默认以单 worker 运行，多扫描器仍依靠行锁避免重复恢复。

后端类型检查：`uv run --project backend ty check backend/src/shop_api`。
