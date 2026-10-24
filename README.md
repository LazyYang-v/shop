# 淘宝风格单商家电商作品集

后端已覆盖首版商城闭环：商品与库存管理、购物车和地址、结算与模拟支付、取消及超时关闭、订单查询、管理员发货和买家确认收货。前端提供商品发现、主题频道、个人中心、地址簿、购物车、地址选择/新增、下单后跳转我的订单、模拟支付/取消/确认收货和物流详情，并已接入管理员商品、库存与订单发货页面。帮助中心、公告和分类导航提供完整访问入口；整站真实数据库发货到收货的完整验收仍待完成。

## 客服演示与验收

客服当前使用虚构商品、专用买家和明确标注的合成政策；确认及结果核验复用商城权限与取消事务。真实商城政策和真实 WeKnora 产品入口保持关闭。组合演示、桌面/移动复现命令、黄金/边界/回归/安全场景及实际结果见[客服最终评测](docs/customer-service-final-acceptance.md)，外部能力证据与未完成门槛见[WeKnora 能力矩阵](docs/customer-service-weknora-acceptance.md)。默认运行范围及冻结参数以[客服运行契约](docs/customer-service-runtime-contract.md)为准。#9 已完成[隔离部署与新卷恢复验收](deploy/customer-service-demo/ticket-9-acceptance.md)，本机入口为 http://127.0.0.1:18011/customer-service.html；真实首版仍需[批准资料与工程证据](docs/customer-service-real-release-prerequisites.md)。

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
