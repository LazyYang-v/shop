# 商品照片来源与维护

当前演示目录为 **113 件商品 / 113 张实际照片 / 15 个分类**：85 张已下载的 Pexels 照片和 28 张继承照片。每张照片只对应一个在售演示商品，不再按前缀生成变体。商品名称按实际画面人工核对；价格、库存和描述为本地演示数据，不代表摄影平台销售这些商品。

权威清单为 [`backend/src/shop_api/demo_product_manifest.json`](../../../backend/src/shop_api/demo_product_manifest.json)。该清单以完整商品名称为键，逐项记录分类、图片路径、价格、初始库存、SHA-256、宽高及来源。后端将图片映射暴露为只读映射，调整目录须显式修改清单，不能按排序或编号重新分配图片。

Pexels 文件名中的数字为照片 ID；清单内对应 `https://www.pexels.com/photo/<ID>/`，使用条款见 [Pexels License](https://www.pexels.com/license/)。其中 72 张为原有本地照片，本次另从 Pexels CDN 下载 13 张独立实拍，逐张查看并核对名称，新增条目保留完整 `download_url`。每个下载候选使用独立空暂存目录，未采用生成图片，未将婴儿肖像当作护理商品，也未将宠物肖像当作宠物用品。多张同一商品不同角度的候选只选一张。

本次补齐汽车、医疗健康、工业品，各新增 3 件；男装从 3 件增至 5 件，图书从 1 件增至 3 件。新增照片来源及对应商品如下：

| 分类 | 商品 | Pexels 照片 |
| --- | --- | --- |
| 汽车 | 乘用车橡胶轮胎 | [6870311](https://www.pexels.com/photo/6870311/) |
| 汽车 | 汽车启动蓄电池 | [4374843](https://www.pexels.com/photo/4374843/) |
| 汽车 | 汽车轮毂细节清洁刷 | [6872147](https://www.pexels.com/photo/6872147/) |
| 医疗健康 | 便携电子体温计 | [3938415](https://www.pexels.com/photo/3938415/) |
| 医疗健康 | 蓝色耳挂式防护口罩 | [5040593](https://www.pexels.com/photo/5040593/) |
| 医疗健康 | 红管双头听诊器 | [5149754](https://www.pexels.com/photo/5149754/) |
| 工业品 | 充电式手持电钻 | [11398216](https://www.pexels.com/photo/11398216/) |
| 工业品 | 金属开口维修扳手 | [5794263](https://www.pexels.com/photo/5794263/) |
| 工业品 | 管钳羊角锤卷尺工具组合 | [8488061](https://www.pexels.com/photo/8488061/) |
| 男装 | 红蓝格纹休闲衬衫 | [18533673](https://www.pexels.com/photo/18533673/) |
| 男装 | 白色长袖通勤衬衫 | [5409187](https://www.pexels.com/photo/5409187/) |
| 图书 | 复古精装阅读书籍组合 | [192928](https://www.pexels.com/photo/192928/) |
| 图书 | 外文平装阅读书籍组合 | [7095568](https://www.pexels.com/photo/7095568/) |

照片展示商品实物或使用场景；图书按可见装帧与语言命名，没有虚构书名，医疗健康用品未据照片添加认证或疗效承诺。未采用香水瓶占据主体的白衬衫候选。本次已通过 `--archive-only --apply` 同步本地 shop_dev，新增 13 件商品及 13 条初始入库流水，没有删除任何记录或重置原商品库存；最终在售 113 件，覆盖 15 个分类。分类筛选与所有在售图片加载已通过浏览器验证。下文 100 件在售及 88 条入库流水记录属于此前的整理结果。

部分继承照片有先前记录的 Unsplash CDN ID，清单保留其精确 CDN 地址，条款见 [Unsplash License](https://unsplash.com/license/)。另有继承照片缺失原下载地址，清单用 `source_status` 明确标记、来源地址及许可字段留空，不能宣称它们是新下载的 Pexels 照片。若准备公开分发，先补全这些文件的原始来源及许可记录。

之前的来源表存在错误：`journal.jpg` 实际是纸袋，`roasted-almonds.jpg` 是饼干，`assorted-nuts.jpg` 是早餐谷物碗，`hat.jpg` 是棒球帽，`tote.jpg` 是编织拼接包。`charger.jpg` 是手机，现对应手机商品；`mug.jpg` 只对应杯具。`organizer.jpg` 和 `workshop.jpg` 是作业现场，未用于商品。`shoes.jpg` / `sneaker.jpg` 为字节完全相同的照片，只使用前者；`phone-charger-on-desk.jpg`、`wireless-earbuds-closeup.jpg` 是旧图的其他编码，未重复使用。未使用的候选文件保留，但不进入目录。`abo/` 中的六张候选没有采用，也没有作为本次照片来源；已移除失败的 ABO 自动匹配脚本。

## 纯本地验证

在项目根目录执行（无需数据库、Docker 或网络）：

```sh
uv run --project backend python -m shop_api.reconcile_demo_catalog --validate-images public
```

此命令校验每个路径、JPEG 尺寸、清单哈希、最小边长 200 像素，以及图片路径和内容哈希唯一性。清单只含人工确认的条目，不自动拿其他照片填补缺失项。

## 安全整理本地开发库

设置 `SHOP_DATABASE_URL` 指向 `127.0.0.1:55444/shop_dev`（使用本地数据库用户名和密码；不要提交密码）。整理命令仅接受 PostgreSQL、回环地址和数据库名 `shop_dev`，拒绝 URL 查询参数覆盖连接目标。默认只查询并打印 JSON 计划，**必须显式传入 `--apply` 才提交事务**：

```sh
# 预览：更新保留商品、补齐新商品、清理已知旧演示商品
uv run --project backend python -m shop_api.reconcile_demo_catalog

# 保留所有旧记录，仅下架多余商品并补齐新商品（本次实际采用）
uv run --project backend python -m shop_api.reconcile_demo_catalog --archive-only --apply

# 删除没有任何关联记录的多余商品；有关联记录的仍然只下架
uv run --project backend python -m shop_api.reconcile_demo_catalog --apply

# 可选：仅更新现有元数据、图片及上下架状态，不创建商品或库存记录
uv run --project backend python -m shop_api.reconcile_demo_catalog --metadata-only
uv run --project backend python -m shop_api.reconcile_demo_catalog --metadata-only --apply
```

`--metadata-only` 只更新现有商品元数据和上下架状态，所有多余行仅下架，不删除、不创建商品、不调整库存、不写库存审计。若只需更新已知目录而不整理旧数据，可使用现有 `seed-demo-products` 命令，但它会为缺少的商品创建初始库存。

退役范围使用 [`retired_demo_names.json`](../../../backend/src/shop_api/retired_demo_names.json) 中固定的历史名称清单，包括旧 435 个演示名称和六个更早的演示名称；绝不按分类批量操作，也不匹配任意管理员商品。相同名称的重复行保留创建时间最早的一行，其余进入退役流程。隐藏的旧行也会被检查。

命令通过数据库外键元数据检查所有引用 `products.id` 的表。已知外键包括 `cart_items.product_id`、`order_items.product_id` 和 `inventory_adjustments.product_id`，后者为 `ON DELETE RESTRICT`。有任意引用的退役商品只设 `is_listed=false`，JSON 计划列出引用表和计数；没有引用才删除。绝不为删除商品而删除订单、购物车或审计记录。由于旧种子商品通常带初始入库审计，很多旧行会留在数据库中但不再展示。

保留商品更新分类、描述、图片、价格和上架状态，**库存为零也不自动补货**。新商品才创建初始库存及审计，因此完整应用需要有效管理员；仅更新模式不需要管理员。操作在单一事务中完成，错误整体回滚。本次已在本地 shop_dev 执行 `--archive-only --apply`：更新 12 件、新增 88 件、下架 429 条旧记录、物理删除 0 条；最终在售 100 件。原有订单、订单项、购物车和库存流水均保留，新增商品增加 88 条初始入库流水。
