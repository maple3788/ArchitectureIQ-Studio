# 知识演化实时观察接入

## 目标与设计

以持续生成新题、复验命题、统计判定、提出修订的服务器循环为 Harness 主线路，入口名为“知识演化”。保留原工作流编辑与历史记录，既有草稿和冻结引用不迁移、不覆盖。

UI 首屏为同步状态、本轮真实出题进度、七阶段画布；画布下方为知识进展与轮次记录。节点详情显示保存的产物，命题详情显示适用条件、登记后证据和修订历史。候选、已验证、存疑、停用均沿用来源记录，不在 Studio 重新判定。检查属于 propose 的内部步骤；无单独检查完成标记。

以只读观察接入现有运行，不启动、停止或修改远程实验。连接信息放私有部署配置；读取脚本在 Studio 内维护，远程执行脚本只读取白名单文件与进程存活证据，不导入旧仓库代码。服务器断开时保留上次记录并显示失联；阶段完成只来自 DONE 标记，运行中还要求进程存活证据。未持久化的模型输出不模拟展示。

## 接口约定

`GET /api/studio/kb-loop` 与 `/stream?after=N` 返回相同公开快照，SSE 名称 `snapshot`、id 为持久化 sequence。同步心跳另用 `sync` 事件。GET `/claims/{id}` 与 `/rounds/{index}` 返回持久化的详情；客户端不能传路径或执行命令。

快照：`configured, name, sequence, sync{status,last_success_at,last_attempt_at,message?}, captured_at, source_updated_at, execution{status,stop_requested,alert}, round{index,completed_stages,next_stage,plan{total,target,explore},build{completed,ok,failed}}, kb{claims,candidate,verified,flagged,retired}, evidence{questions,verdicts}, claims[], rounds[], thresholds`。

命题：`id,version,text,rules,status,registered_round,needs_revision,revisions,stats,parent,rationale,consistency,evidence{applicable,support,refute,conflicts}`。证据计数仅当前修订、登记之后的题目，stats 直接来自上游判定。详情：`claim,history,evidence,evidence_total,evidence_truncated`，证据是最近 100 条，含题号、轮次、支持/推翻、比较关系与题目公开候选；不发送训练产物路径或凭据。

轮次列表：`index,completed,completed_stages,plan,build,report`。详情增加 `score,judge_events,proposals{new_count,revision_count,rejections,qwen},registration{count,hash,hash_matches},registered`。阈值只读取冻结配置中的 judge 字段。完整来源内容和连接配置不暴露到 API。

采集脚本返回快照业务字段，加内部 `claim_details`、`round_details` 两个映射。观察器将整个采集结果作为持久化捕获；公开快照排除详情映射。仅内容变化追加事件，同步成功时间单独更新。失败保留前次完整捕获，错误消息不含远程路径或原始异常。

## 实施与验证

- [x] 1. Studio 白名单采集器：真实阶段、出题去重、登记后证据、历史与报告、安全读取；模拟文件测试覆盖半行、来源写入中、散列不符和来源无写入。
- [x] 2. 私有配置、SSH 只读传输、持久化观察日志和 SSE：断线保留、游标重放、脱敏、单采集循环；加入 API 与重连测试。
- [x] 3. 知识演化页面、七阶段画布、知识/轮次详情：配置连接后默认进入；旧编辑器保持惰性挂载；测试断线、候选统计与旧草稿保护。
- [x] 4. 在本地连接真实服务器，只观察真实运行；检查布局与实时更新，核对当前草稿未变；全前端测试、针对性后端测试与构建通过后同步 GitHub。

## 重点边界

JSONL 尾部未完成记录不能计入；其他损坏不静默吞掉。失败重试后成功的出题记录以成功为准。来源不具备事务快照能力，采集期间文件改变则重试，不展示混杂数据。进程未知不能当成正在运行；无新观测不能当成停止。统计下界缺失显示等待判定，不以 0 代替。外部循环的历史证据只用于研究观察，不送入现有 Solver 或自动发布到 KB。
