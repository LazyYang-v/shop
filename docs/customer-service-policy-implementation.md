# 客服 #4 合成政策问答实施记录

日期：2026-10-23。状态：**合成演示路径已实现，并通过本地 API/真实 Chrome/UI 测试及隔离演示容器内验收；真实商城政策与 WeKnora 路径仍关闭。#4 已关闭。**

关联：GitHub `LazyYang-v/docs#4`、[运行契约](customer-service-runtime-contract.md#2026-10-23-4-合成政策演示真实政策路径仍关闭)。范围修订明确只使用合成规则，不写入当前共享 WeKnora，不宣称生产政策覆盖，也不新增付费模型调用。

## 实现边界

- **权威登记与索引分离**：`deploy/customer-service-demo/policies.synthetic.v1.json` 是受文件 SHA-256 约束的合成登记。每条登记包含 `policy_id`、`version`、`scope_key`、`source_label`、受限 `source_ref`（只允许 `synthetic://`）、`effective_from/effective_to`（UTC `[from,to)`）、`status`、`knowledge_base_id`、`knowledge_id`、规范正文及正文 SHA-256。索引替身只保存检索候选文本；回答和引用正文只取登记规范正文。
- **发布检查**：加载时拒绝非合成标签、真实 URL、非批准 KB、重复 policy/version 或文档映射、空/无效区间、活动区间重叠、正文哈希不符、活动政策缺少已核实索引文档、研究资料混入政策库。
- **检索后核对**：只按返回的 KB+文档 ID 查询登记；撤回、过期、未来、未知映射和删除残留不授予回答资格。索引中的高分、摘要、版本自称或指令文本均不能替换登记。
- **交付前复核**：构造引用前再次检查同一版本仍活动、状态未撤回、正文哈希一致；撤回发生在检索与交付之间时返回 `policy_unavailable`。
- **四类结果**：HTTP `status` 使用既有词汇 `ok`、`empty`、`unavailable`，并以不同 `code` 区分 `policy_no_match`、`policy_conflict`、`policy_unavailable`。无法唯一解析政策主题时返回 `needs_clarification`。检索没有返回候选但登记中仍有当前活动版本时返回 `policy_unavailable`，不误报为无匹配。冲突只可能来自损坏的权威登记（正常发布校验会拒绝重叠区间），测试通过故障注入覆盖；冲突不交给模型择一，该路径不调用模型。
- **来源可核对**：答复引用含 `policy_id`、`version`、`source_label`、`source_ref`、生效区间、规范正文及哈希，并始终标注“虚构演示政策（非真实商城政策）”。
- **外部研究资料**：只进入独立研究集合（不同 KB），不进入政策索引；没有政策依据时仅提示“标注为非商城政策的研究资料，不能作为商城政策依据”，不引用其正文。
- **配置关闭语义**：未配置 `SHOP_CUSTOMER_SERVICE_POLICY_PATH/SHA256` 时政策保持 `policy_unavailable`；仅配置一半或文件/hash/标签/发布检查失败时客服整体 fail-closed，不启用政策。没有 WeKnora 客户端、端点、令牌或网络调用。
- **演示接线**：`compose.products.yaml` 以只读方式挂载合成 fixture 并注入路径/哈希；预检脚本验证合成标签、来源、研究资料隔离及 API 环境无 WeKnora/模型/令牌变量。已从提交 `1cf69a1` 的干净归档构建 `shop-customer-service-demo-api:20261023-policy`（镜像 ID `sha256:7cd1878d5b7986eb20164b9ce1dfe71eb90b0501294fd60266dd954665ca3fe8`），仅重建主演示项目的 `shop-api` 与 `shop-web`；保留原数据库卷和日志卷，未删除或重置数据。重建 Web 是为刷新旧 bind-mount inode，使浏览器加载当前页面；未改变项目资源范围。

## 测试证据

| 项目 | 命令/入口 | 实际结果 |
|---|---|---|
| 合成政策模块/API/启动 | `pytest backend/tests/test_customer_service_policy.py backend/tests/test_customer_service_startup.py` | 26 passed；覆盖发布冲突、正文哈希、非合成来源、旧/未来/删除残留、no-match/冲突/不可用、活动版本检索缺失、交付前撤回、索引注入、无模型调用、启动 fail-closed |
| 完整后端回归（含真实 Chrome） | `SHOP_RUN_BROWSER_TESTS=1 pytest backend/tests` | **318 passed**，2 项依赖弃用警告，65.74s；真实 Chrome 桌面/移动覆盖商品、合成政策引用、no-match 及注入哨兵 |
| 前端 Playwright | `playwright test e2e/customer-service.spec.ts` | 15 passed；新增政策引用渲染与未标注引用拒绝 |
| 隔离演示容器内 API 矩阵 | 直接请求 `127.0.0.1:18011` | 4/4 通过：发货 v2 引用；包邮残留 `unavailable/policy_unavailable`；礼品包装 `empty/policy_no_match`；歧义 `needs_clarification`；无哨兵 |
| 隔离演示容器内真实 Chrome | `SHOP_BROWSER_TEST_ORIGIN=http://127.0.0.1:18011 node e2e/customer-service-real.mjs` | 桌面/移动均通过；商品事实、合成政策引用、no-match、注入文本及跨会话拒绝；0 模型/0 WeKnora |
| 容器日志与秘密隔离 | `docker exec ...` 只读检查 | 20 条 JSONL、0600、仅允许字段；工具含 `search_policy`；`PRIVATE_POLICY_SENTINEL`/`PRIVATE_RESEARCH_SENTINEL`/政策正文均为 0；API 无 WeKnora/模型/令牌环境变量，仅 internal 网络 |
| 静态部署预检 | `python3 -I deploy/customer-service-demo/preflight.py` | 通过；默认 0 服务、合成 fixture 标签/hash、只读挂载、无 WeKnora/模型/令牌变量 |
| 类型检查（变更范围） | `ty check customer_service_policy.py app.py customer_service_consultations.py` | 新增模块 0 诊断；仍保留既有 `pages.remove` 两项诊断（未修改该逻辑） |
| 付费调用 | — | **0 次**；政策路径无模型 transport，浏览器测试用“被调用即失败”的哨兵验证 |

测试只在 `127.0.0.1:55445/shop_test` 及隔离真实 Chrome 中执行；`SHOP_ALLOW_TEST_DATABASE_RESET=1` 仅传入测试子进程。未修改开发库/演示库，未启动新容器，未写入 WeKnora，未保存秘密。

## Acceptance criteria 对照

1. **登记标识/来源/版本/区间/状态；WeKnora 只作索引；前置核实接口权限** — 合成登记字段、发布校验、KB+文档 ID 映射已实现；真实 WeKnora 仍关闭且未接入。合成边界不声称完成真实端点权限核实。
2. **发布区间冲突；检索后核对；旧/未来/删除/失效历史不能作为当前依据** — 通过模块与 API 测试覆盖。
3. **无匹配/冲突/不可用分别呈现；不以常识补全；冲突不由模型择一** — 通过既有 `status` 词汇配不同 `code` 与固定措辞验证；冲突路径通过损坏登记故障注入覆盖；政策路径不调用模型。
4. **可核实来源/版本/生效依据；外部文章标注非商城政策且不进入政策索引** — 引用字段及前端渲染验证；研究资料独立 KB 且不引用正文。
5. **演示/API/浏览器覆盖版本、故障、政策注入、秘密隔离；索引文本不能成为指令** — 已在重启后的隔离演示容器内完成 API 矩阵与真实 Chrome 桌面/移动验收；注入哨兵未进入答复、日志或模型；无秘密进入响应或日志。容器内日志仅允许字段，API 环境无 WeKnora/模型/令牌配置。

## 限制与未完成

- 没有真实批准政策、真实来源治理或生产问题集；合成规则只用于隔离演示，不能当作商城政策承诺。
- 未连接 WeKnora；真实 KB 隔离、令牌权限、超时/限流/降级、索引清理与召回质量仍按运行契约阻塞。
- 演示 Compose 已完成静态预检及主演示容器内验收；新 API 镜像为本地构建，未推送到远程镜像仓库。验收针对该镜像 ID 和哈希固定的合成 fixture，不代表真实政策或真实 WeKnora 能力。
- 没有新增付费模型调用；政策路径不使用模型，因此“模型不得自行择一”由结构保证而非模型行为评测。
- 交付复核与 HTTP 发送之间仍有极短窗口；本实现只保证复核时刻状态，不追溯撤销已发出的字节。

## 结论

合成政策问答路径在受控演示范围内完成，并通过本地及容器内 API/浏览器证据；真实政策路径继续保持关闭。#4 已于 2026-10-23 关闭，最终验收评论见 https://github.com/LazyYang-v/docs/issues/4#issuecomment-6360893082 。
