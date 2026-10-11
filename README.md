# ArchitectureIQ Studio

ArchitectureIQ Studio 是一个围绕 **Data → Harness → KB → Task** 的研究工作台，用于管理题目、配置模型与工作流、积累知识，以及查看运行结果。

项目包含 React / TypeScript 前端、Python API、工作流协调器和知识存储。基准引擎随源码提供，保持「规格 → 生成代码 → 执行 → 存储结果」的一致性，无需依赖其他工作目录。

## 主要功能

- **Data**：管理题目目录、导入来源和不可变题集。
- **Harness**：选择 Dataset、模型和处理步骤；通过规则闭环执行 KB、收集反例、修订并验证新版本。
- **KB**：阅读正式知识、学习经验和研究规则，查看固定版本、验证证据与适用题目。
- **Task**：在独立题集上检查冻结知识；研究规则评测直接执行程序规则，无需作答模型。

[规则发现与迭代](docs/rule-refinement.md) 由程序负责预测和评分，模型只负责初始化与修订规则。新题首测和累计研究成绩分别保存。

默认的「单题学习」流程先提交答案，再读取已存储的反馈并提炼经验。后续轮次可以继续使用同一道题和此前的经验；重复练习不代表在独立题目上的评测提升。高级配置保留科学研究和成对实验方法。

运行状态和输出来自后端持久化事件。题目答案与反馈在作答提交之前保持隔离，学习经验会明确标注其验证状态。

## 本地启动

建议使用 Python 3.12+、Node.js 20+ 和 `uv`。

在项目根目录执行：

```bash
bash scripts/setup.sh
cp .env.example .env
bash tools/studio_server.sh
```

打开 <http://127.0.0.1:8094/#workflow>。

启动脚本会检查 Python 模块是否来自当前项目。可通过 `STUDIO_PYTHON_VERSION` 选择安装时使用的 Python 版本，或通过 `STUDIO_PYTHON` 指定已有解释器。

本地支持界面编辑、规则匹配预览、使用已有存储结果的纯规则评测，以及构建和模拟测试。真实模型调用及生成代码实验仅在经授权的 Linux 执行环境中进行。

## 配置与数据

将运行配置保存在本地 `.env` 中。以下变量用于指定数据位置，请根据自己的环境填写绝对路径：

| 变量 | 用途 |
| --- | --- |
| `STUDIO_STATE_ROOT` | 工作台运行状态与结果目录 |
| `STUDIO_SOURCE_ROOTS` | 允许导入的外部数据目录 |
| `STUDIO_ARCHIVES` | 只读历史运行目录 |
| `STUDIO_HOST` | API 监听地址，默认 `127.0.0.1` |
| `STUDIO_PORT` | API 监听端口，默认 `8094` |

源码不包含私有题库或模型凭据。可通过导入工具查看可用选项：

```bash
PYTHONPATH=src .venv/bin/python tools/studio_import_sources.py --help
```

工作流草稿由后端保存，并在不同浏览器之间同步。修改有版本冲突时，界面会提示选择；提交的运行配置和起始知识版本会被冻结，以便追溯。

部署时通过私有配置提供执行环境和数据路径。为新版本使用独立源码目录，并保留历史运行所依赖的冻结源码与数据。源码迁移的文件校验记录位于 `migration/source-manifest.json`。

真实执行还要求 `ARCHITECTURE_IQ_KB_AUTHORIZED_HOST` 与 `ARCHITECTURE_IQ_KB_EXECUTION_HOST` 均非空且完全匹配，并且系统为 Linux。仅在授权执行服务器的私有环境中设置这两个变量；默认不启用真实执行。部署记录和内部计划保留在本地，不加入 Git。

## 模型接入

在 **模型 → 登记模型** 中选择 **自部署模型** 或 **API 接入（兼容 OpenAI）**。API 接入需要填写配置 ID、显示名称、请求模型 ID、服务地址和 API Key。服务地址应包含服务商要求的 API 前缀，例如 `https://your-provider.example/v1`。也可以填写服务端的凭据环境变量名；两种凭据来源选择一种即可。

保存后点击 **检查**，再在 **单题学习 → 作答** 中选择该模型。检查会使用凭据读取 `/models`，确认服务公布了请求模型 ID，不发送聊天请求，也不验证推理质量。服务需要支持 `/models` 和流式 `/chat/completions`。模型别名返回的实际版本 ID 会原样保存在收据中；同一次流中途变换模型仍会被拒绝。

API 模型可用于单题学习、普通评测和规则初始化与修订，明确标记为 **API 服务，权重身份未验证**。运行冻结服务地址、请求模型名、参数、配置版本和凭据引用，不将服务商权重视为已验证或固定。科学及成对研究仍需原有的自部署运行锁。真实调用仍只在授权 Linux 执行环境运行；本地可以编辑和预览配置。

界面输入的密钥只保存在 `STUDIO_STATE_ROOT/credentials/` 中，目录权限为 `0700`，密钥文件权限为 `0600`。密钥不会回显，也不进入模型 JSON、运行配置、收据、浏览器存储或 Git。编辑时留空保留已保存密钥；更新密钥会生成独立凭据版本，已冻结任务保留原引用。旧密钥若被服务商撤销，旧任务仍可能调用失败。更换服务地址时需要重新填写密钥。凭据目录应随服务端状态私密备份，配置界面供可信操作人员使用。

## 开发与检查

```bash
# 确认模块来自当前项目
PYTHONPATH=src .venv/bin/python -c 'import architecture_iq; print(architecture_iq.__file__)'

# 本地模拟测试
PYTHONPATH=src .venv/bin/python -m pytest tests/test_basic_learning.py
npm --prefix frontend/workflow test

# 前端构建与启动检查
npm --prefix frontend/workflow run build
bash tools/studio_server.sh --check
```

前端开发模式：

```bash
npm --prefix frontend/workflow run dev
```

开发界面默认使用 `http://127.0.0.1:5174`，API 默认代理到本地 `8094` 端口；可通过 `STUDIO_API_TARGET` 指定其他地址。

请勿将凭据、运行状态、私有数据集、模型权重或构建缓存加入 Git。涉及真实推理或训练的检查应在授权执行环境中运行。

## 许可证

见 [LICENSE](LICENSE)。
