# 开发说明

## 本地环境

主 Agent 依赖 MatSimPy 的 `Agent`、`ChatProvider` 和 `ToolCatalog`。当前通过验收的 MatSimPy 版本为 0.11.0，对应源码提交 `d4bd33ba608b3dbf9253340b62a7ee45719c793e`。从项目根目录执行 `python -m pip install -e ../matsimpy -e .` 可注册本地源码和命令行入口。

现有 WSL 工作区可以直接使用已经配置的 Python 环境。在项目根目录执行下列命令，使用源码运行，无需先安装本项目。

```bash
PYTHONPATH=src:../matsimpy /home/administrator/software/UniMatSim/.venv/bin/python -m matagent --demo --workspace examples/mos2 "上次 MoS₂ 优化收敛了吗？最终最大原子力是多少，证据在哪？"
PYTHONPATH=src:../matsimpy /home/administrator/software/UniMatSim/.venv/bin/python -m unittest discover -s tests -v
```

若使用其他解释器，需要先安装 `pyproject.toml` 声明的依赖。参考运行可直接用于查询与测试。执行新的 MoS₂ 优化还需要相邻的 UniMatSim 源码、相应计算依赖和本地检查点，具体要求见[优化文档](mos2.md)。

## 代码职责

| 文件 | 职责 |
|---|---|
| `src/matagent/assistant/agent.py` | 中文系统提示、项目工具注册、请求授权和工具调用轮数上限 |
| `src/matagent/cli.py` | 终端参数、工作目录和调用轨迹 |
| `src/matagent/assistant/config.py` | 环境变量与用户本机模型配置的读取 |
| `src/matagent/execution/run_tools.py` | 列出运行、按编号读取记录、化学式筛选与证据路径解析 |
| `src/matagent/optimization_tools.py` | 计划预览、执行授权与固定样例入口 |
| `src/matagent/assistant/conversation.py` | 会话引用解析、工具结果持久化与旧会话迁移 |
| `src/matagent/physics/guard.py` | 共享几何、权重、收敛核对及单结构检查工具 |
| `src/matagent/assistant/demo_provider.py` | 可注入的离线测试模型 |
| `tests/test_agent.py` | 使用临时工作目录执行回归 |
| `examples/mos2/run.py` | 通过单个 YAML 工作流执行与记录 MoS₂ 优化 |

`build_agent(provider, workspace=...)` 接收模型对象与运行工作目录，便于注入其他 `ChatProvider` 实现。项目工具通过 MatSimPy 的 `@tool` 签名和说明向模型暴露参数、结果含义及是否启动计算。工具结果回到模型后，模型生成最终答复。

`--workspace` 默认取启动时的当前目录，工具读取其中的 `runs/<run_id>/run.json`。每条记录中的产物路径相对于该次运行目录，工具返回的证据路径相对于工作目录。

## 测试与打包

从项目根目录执行 `python -m unittest discover -s tests -v`。参考数据位于 `examples/mos2/runs/`，测试会复制到临时目录。

标准 Python 构建入口由 `pyproject.toml` 定义。源码发布包包含文档、测试和固定的参考样例，wheel 包包含 `matagent` 源码与命令行入口。

## 文件位置调整

| 原入口或文件 | 当前入口或位置 |
|---|---|
| `python ask.py ...` | `matagent ...` 或 `python -m matagent ...` |
| `python run_mos2.py` | `python examples/mos2/run.py` |
| `workflow.yaml` | `examples/mos2/workflow.yaml` |
| `python -m unittest -v test_agent` | `python -m unittest discover -s tests -v` |

真实模型配置支持环境变量及用户配置文件，现有运行记录可由工作目录参数定位。

## 真实模型联调

本机的 MatSimPy 和 2D-MatAgent 已以可编辑方式安装到现有 WSL Python 环境。新终端可使用以下命令。

```bash
source /home/administrator/software/UniMatSim/.venv/bin/activate
cd /home/administrator/agent/2D-MatAgent
matagent --workspace examples/mos2 "上次 MoS₂ 优化收敛了吗？最终最大原子力是多少，证据在哪？"
MATAGENT_LIVE_TESTS=1 python -m unittest discover -s tests -v
```

本机配置保存在用户目录 `~/.config/2d-matagent/model.json`，目录权限 700、文件权限 600。当前选择 `deepseek-v4-pro`、低推理强度和 DeepSeek 官方服务。后续真实模型验收读取同一份本机配置，环境变量可以覆盖本机设置。

2026 年 11 月 21 日（北京时间）完成真实验收，共 7 项测试通过。最近 MoS₂ 查询产生 `list_runs(formula="MoS2", limit=1)` 和 `read_run`，最终最大原子力及证据路径与真实记录一致。不存在的编号查询产生 `read_run` 并正确返回缺失信息。两次请求合计 API 报告用量 5907 tokens，运行文件的 SHA-256 在验收前后相同。

`tests/test_live_agent.py` 通过正式命令行入口发出两次查询，并核对会话中的工具参数、返回值、回答和模型用量。会话记录位于样例工作目录的 `.matsimpy/sessions/`。

优化计划与执行的交互命令、参数约束及本机第 4 步验收见[优化计划文档](plans.md)。

第 5 步输入与结果检查的字段、状态和真实模型验收见[PhysicsGuard 文档](physics_guard.md)。

第 6 步交互入口、恢复命令、真实对话和 v1 限制见 [会话与交付说明](conversations.md)。原生消息继续使用 MatSimPy 的 Session、save 和 resume；引用与中断前的工具结果保存在同编号的 .matagent/sessions 文件中。

## 第 7 步结构建模

`structures/tools.py` 提供八个建模工具；`structures/store.py` 保存结构、来源与父子关系；`structures/geometry.py` 提供与原 PhysicsGuard 共享的几何核对。现有 `assistant/conversation.py` 为结构、计划、运行分别管理引用，并兼容旧会话的缺省字段。

几何编辑使用已有 MatSimPy，二维等价位点使用已安装的 spglib 2.7.0 的层群接口。没有新增依赖或模型。完整使用方式、原型来源和真实验收见 [结构建模说明](structures.md)。

## 第 8 步势模型发现与选择

`potentials/catalog.py` 提供全后端能力表和静态识别，`potentials/store.py` 管理内容哈希登记和项目偏好；`potentials/validation.py` 调用独立的 `matagent.potentials.worker` 进程，仅加载所选权重。`potentials/tools.py` 注册五个自然语言工具，conversation 将模型选择与结构、运行引用分别保存。

离线测试覆盖所有类型的能力映射、识别冲突、文件变化和异常加载。真实验收通过 MATAGENT_LIVE_POTENTIALS=1 开启，使用已配置的模型服务和现有本地权重，不启动材料计算。详细行为见 [势模型说明](potentials.md)。

## 第 9 步自动生成 YAML

`planning/plan_tools.py` 扩展预览工具并增加更新、读取和校验工具；`planning/single_task.py` 管理版本化定义、确定性 YAML 和产物核对；`matagent.planning.plan_backend` 在独立进程中调用 UniMatSim 结构读取及配置解析接口；`matagent.plan_cli` 提供不依赖语言模型的校验和重新编译命令。

通用参数与几何检查复用 physics_guard。conversation 独立解析计划、结构、模型和历史运行引用，保存待补字段；计划查询强制读取本轮文件证据。旧计划无需迁移，新计划用 schema_version=2 和 kind=single_optimization 区分，执行入口在创建 execution 目录前拦截新类型。

配置解析使用工作区的相邻 UniMatSim 源码，与原执行入口保持一致。模型证据来自第 8 步，预览不重新加载。测试分别覆盖五后端的实际配置解析（模拟加载证据）和真实 DeepSeek + 已验证 MatterSim 权重的完整对话。详情与命令见[单任务 YAML 说明](plans.md)。


## 第 10 步 DAG 规划

源码版本 1.4.0；主入口沿用现有 Agent。开发与验收见 [workflows.md](workflows.md)，参数覆盖见 [capabilities.md](capabilities.md)，上游改动边界见 [upstream-step10.md](upstream-step10.md)。新通用计划仅配置，不接入材料执行。

## 分发包与子进程

在已安装项目依赖和 setuptools ≥ 77 的环境中，从项目根目录构建 wheel：

```bash
python -m pip wheel --no-deps --no-build-isolation --no-index . -w dist
```

用另一个准备好依赖的环境安装 wheel，切换到仓库外的工作目录，清除指向项目源码的 `PYTHONPATH`。运行 `python -c "import matagent; print(matagent.__file__)"` 应指向该环境的 `site-packages`。两个终端入口共用同一个 Agent；`python -m matagent.plan_cli validate` 和 `compile` 用于验收工作区内已保存的计划。

| 父进程操作 | 子进程模块 | 可核对的产物 |
|---|---|---|
| 明确验证本地权重 | `matagent.potentials.worker` | 加载状态、实际设备、验证编号及日志 |
| 校验单任务 YAML | `matagent.planning.plan_backend` | 上游解析报告及单节点执行顺序 |
| 校验 DAG 的原生节点 | `matagent.planning.workflow_backend` | 原生配置解析结果与输入绑定 |
| 执行已授权的计划 | `matagent.execution.worker` | 根运行记录、各节点记录和原始结果 |

源码检出优先使用相邻的配套后端。wheel 使用当前 Python 环境中可导入的 MatSimPy 和 UniMatSim。运行时能力清单读取后端源码，`docs/capabilities.json` 保存开发时的快照。固定 MoS₂ 输入随 wheel 安装至 `share/2d-matagent/mos2`，用户工作区保存会话、计划和运行输出。更换解释器或验证器后，先检查旧权重证据的有效性，按需显式重新验证。
