# Issue #1 外部保留与部署期限核实

> 历史记录：保留当轮观察及授权边界；2026-10-23当前范围、已批准参数、证据进展与#1关闭建议以[最终运行契约](customer-service-runtime-contract.md)为准。下文阶段性的OPEN/未授权/待冻结不作为当前结论；实际未验证能力仍受该契约的运行门槛约束。

日期：2026-10-22。只读核实，无收费模型调用、知识库写入、配置变更、故障注入或压力探测。结论包含明确未决项，不能作为商城补偿已实现的证据。

## DeepSeek官方材料

实际获取[开放平台服务条款](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html)（页面注明发布2026-04-22、生效2026-04-29）、[通用隐私政策](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html)及[API FAQ](https://api-docs.deepseek.com/faq)。

开放平台条款§3.3要求下游开发者披露个人信息处理规则，并在需要时与平台合作处理访问、更正、删除、保留等请求。§5.5明确：下游应用终端用户的个人信息处理规则不由该通用隐私政策覆盖。因此不能把通用政策中“必要期限”“账号存在期间”等描述当作本商城API请求、响应、日志或备份的固定保留承诺，也不能据此声称API零保留或不用于训练。取得的条款未提供足以冻结这些字段的具体期限。

后续[中英文政策复核](customer-service-deepseek-policy-review.md)补充适用范围：隐私政策开头明确包括SDK/API，下游披露责任不表示API整体被排除。政策存在可能训练及产品退出开关的说明，但API开关适用性及具体期限仍未确认；不得将本段简写解释为通用政策不适用于API。

**状态：仍阻塞外部保留契约。** 需适用于当前API账号/服务的官方数据处理条款或账号可确认设置，涵盖请求与响应、滥用监测日志、备份、训练用途、删除及例外；本轮不联系外部人员，不假定网页材料等于账号合同。已完成的付费测试仅发送合成fixture。

## WeKnora部署只读观察

Docker inspect经内存解析，仅输出允许字段，不保存完整环境或敏感挂载路径：

- app及frontend镜像revision仍为3e22822c1d2397be730c458c7539d0eb8c113a24。
- app配置LOG_LEVEL=debug、GIN_MODE=release，存在Redis地址配置，REDIS_DB=0；这些不证明Redis实际健康、限流走共享存储、有效端点额度或回退是否发生。
- app日志驱动json-file；容器LogConfig未显式提供max-size/max-file。此结果不排除Docker守护进程默认或外部日志回收，但没有证明7天期限。未读取实际日志正文，未证明debug日志已暴露秘密。
- 存在绑定挂载和卷；卷存在不说明备份位置、复制、销毁或保留期限。未读取数据库业务数据或备份。

## MCP代理期限与重试

通过frontend的nginx -T只读展开配置，确认location ^~ /mcp/引入/etc/nginx/api-proxy.conf。直接读取该共享文件的指定指令：

| 指令 | 当前值 | 证据边界 |
|---|---|---|
| proxy_connect_timeout | 30s | 代理连接期限，非整轮客服期限 |
| proxy_read_timeout | 3600s | Nginx相邻读取间隔期限，不是绝对请求总deadline |
| proxy_send_timeout | 3600s | 发送间隔期限，不是绝对请求总deadline |
| proxy_next_upstream | error timeout invalid_header http_500 http_502 http_503 http_504 | 配置具备上游切换条件，不证明POST已重放 |
| proxy_next_upstream_tries / timeout | 3 / 30s | 未启用non_idempotent的实际重试取决于请求是否发送、上游集合等；本轮未触发，不计作三次调用实测 |
| proxy_buffering | off | 缓冲配置，不证明断连能取消检索后端 |

该配置不能承担商城单次5秒检索/整轮期限或最多一次尝试预算。商城需由自身适配层执行期限和请求计数，未确认结束的依赖仍占并发。不能用代理断连推断WeKnora或模型停止。没有修改代理或停止服务；未注入Redis、网络或索引故障。

## 用户补充状态

用户随后确认暂无真实商城政策，DeepSeek后台未找到保留/训练/删除相关说明，WeKnora日志清理与备份保留尚未配置。此为用户报告，不替代对宿主机或外部备份副本的清点。具体后续材料见[处理稿](customer-service-retention-followup.md)；未发送外部询问，未修改部署或启用删除任务。

## 放行结论

已补齐实际代理配置、日志配置和官方材料适用范围证据；外部固定保留期限、日志回收、部署实际限流与故障恢复、取消传播仍未验证。后续商城API最高边界测试须在对应实现存在后执行；不为完成#1提前实现#3/#4，也不以本地模拟服务替代真实平台证据。
