# 知识演化实验运行代码

Studio 已包含服务器十轮实验所用的完整闭环代码。服务器上的历史运行目录、封存记录和原始源码保持原样；后续实验从本仓库准备新的运行目录，不再依赖迁移备份项目。

## 代码位置与流程

`tools/kb_loop/loop.py` 串联研究计划 → 出题 → 规则评分 → 证据判定 → 提出与修订 → 预注册 → 报告。其余同目录模块负责各阶段、模型请求缓存、诊断和持久化。`tools/kb_claim_pairwise_eval.py` 是同一批实验使用的规则执行器，包含参数量比例限制和按数据集计算证据的逻辑。

出题继续调用 `src/architecture_iq` 中已有的 canonical engine：规格 → 生成代码 → 执行 → 保存结果，没有新增训练实现。`profiles/v1.5.yaml` 和现有 prompt 模板随运行目录一起复制。`configs/kb_loop/main500_dataset_ids.json` 只保存基准题目的数据集标识，用于排除重用，不包含题目或答案。

迁移来源和原始文件哈希记录在 `migration/kb-loop-source-manifest.json`，由主迁移清单引用。迁入后添加的执行限制不改写这些原始哈希。

## 配置与准备

`configs/kb_loop/loop.example.yaml` 保留这批实验的科学配置，以占位符替换连接信息。将其复制到私有位置，再填写模型、服务和凭证路径。`base_urls` 填 API 根路径（如以 `/v1` 结尾），请求客户端会追加 `/chat/completions`。数据、题池、运行记录与实际配置均不提交到 Git。

使用已安装本项目依赖的 Python，并明确指定当前仓库的导入路径。以下变量从私有部署配置读取：

```sh
PYTHONPATH="$STUDIO_REPO/src:$STUDIO_REPO" "$PYTHON_BIN" \
  "$STUDIO_REPO/tools/kb_consistency_runtime.py" \
  --source-root "$STUDIO_REPO" --destination "$NEXT_RUNTIME"
```

`NEXT_RUNTIME` 必须是新目录。准备操作仅复制和封存源码，可在本地验证；它不会调用模型或执行 GT。每次代码或策略更新都重新准备目录，不能修改旧运行目录的源码或绑定。

## 在授权服务器启动新实验

真实运行限于授权 Linux 服务器，私有环境变量 `ARCHITECTURE_IQ_KB_AUTHORIZED_HOST` 和 `ARCHITECTURE_IQ_KB_EXECUTION_HOST` 必须非空且匹配。直接使用未准备的源码启动会被拒绝。

```sh
PYTHONPATH="$NEXT_RUNTIME/src" "$PYTHON_BIN" "$NEXT_RUNTIME/tools/kb_loop/loop.py" init \
  --root "$NEXT_RUN" --config "$NEXT_CONFIG" --seed-claims "$SEED_CLAIMS"

PYTHONPATH="$NEXT_RUNTIME/src" "$PYTHON_BIN" "$NEXT_RUNTIME/tools/kb_loop/loop.py" run-forever \
  --root "$NEXT_RUN" --max-rounds 10
```

`NEXT_RUN` 必须尚不存在。种子文件采用 `{"claims": [{"id": "…", "text": "…", "rules": […]}]}` 结构。种子保留历史来源身份，新提出、修订和拆分的知识必须通过绑定当前文字、规则、DSL 和真实预算配置的一致性检查，详见 [一致性运行规范](kb-consistency-runtime.md)。

示例配置第一轮为 30 题试运行，后续每轮 300 题；`--max-rounds 10` 表示本次最多完成十轮。失败重试与停止标记遵循既有流程，不代表总能得到 300 道有效题。

## 状态与网页

每轮的 `plan.json`、出题日志、评分、提案、预注册收据、报告及 `DONE_*` 标记保存在运行目录。状态命令只读，不创建运行记录；其 `round` 表示待处理轮次，不能单独用来判断进程是否仍在运行。

```sh
PYTHONPATH="$STUDIO_REPO/src" "$PYTHON_BIN" "$STUDIO_REPO/tools/kb_loop/loop.py" status \
  --root "$RUN_TO_INSPECT"
```

网页继续通过现有 observer 读取服务器保存的事件和进程状态。本次迁移不会切换网页来源或启动另一批实验；以后启动新实验时，再通过私有 observer 配置明确切换来源，分别保存不同实验的记录。
