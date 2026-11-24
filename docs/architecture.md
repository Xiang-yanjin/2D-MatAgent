# 架构与职责边界

2D-MatAgent 通过同一个终端完成中文对话。以“用刚才的结构先优化，再做单点计算，先给我看计划”为例，主 Agent 解析会话引用并选择工具，规划代码生成 YAML；只有收到明确的执行请求，执行器才会启动工作流。

| 职责 | 入口 | 输入、输出与权限 |
|---|---|---|
| 对话与工具注册 | [主 Agent](../src/matagent/assistant/agent.py)、[会话](../src/matagent/assistant/conversation.py) | 复用 MatSimPy 的模型接口、工具调用循环和会话。将“刚才的”绑定到结构、势、计划或运行，候选有歧义时澄清。 |
| 结构与势工具适配 | [结构工具](../src/matagent/structures/tools.py)、[势工具](../src/matagent/potentials/tools.py) | 将工具参数交给结构登记、MatSimPy 结构 I/O 或本地势模型登记代码，返回对象编号、文件与证据。势模型加载验证在独立进程中完成。 |
| 计划与工作流 | [单任务编译](../src/matagent/planning/single_task.py)、[DAG 编译](../src/matagent/planning/dag.py) | 核对输入、模型和参数，生成版本化计划。根据节点类型生成 UniMatSim 原生 YAML 或含适配器的工作流清单，调用配置校验入口。一次预览可以写计划文件，材料运行数应为零。 |
| 执行授权与调度 | [计划工具](../src/matagent/optimization_tools.py)、[执行器](../src/matagent/execution/runner.py) | 将用户明确的执行意图绑定到指定计划，检查计划和输入后登记运行。重复的同一执行请求复用运行编号；worker 按已保存计划调度 UniMatSim 或已登记适配器。 |
| 物理检查与解释 | [PhysicsGuard](../src/matagent/physics/guard.py)、[节点结果检查](../src/matagent/execution/checks.py) | 对当前二维样例检查面外方向、周期性来源、晶胞约束等条件。从节点证据核对力阈值、最终力、单位和收敛标记，分别报告执行状态和物理结果。 |

## 如何核对一次回答

工作区中的 `.matagent/plans/<plan_id>/` 保存计划定义和实际 YAML；`runs/<run_id>/run.json` 对应一次执行。对“最终最大原子力是多少”，[查询工具](../src/matagent/execution/run_tools.py)按运行和节点读取证据，再把结果交回语言模型。节点日志、原始结果与导出的结构文件各有独立路径。缺失的值应标为缺项。结构优化收敛只支持所用势模型、约束和阈值下的力判据。

CLI 的异常事件由 `matagent` 日志写入 stderr，默认级别为 WARNING。模型调用失败记录事件和会话编号；日志不包含用户提问、模型原始响应或授权头。终端正常回答使用 stdout。节点计算的 stdout、stderr 和原始科学结果仍可按运行记录定位。

更多细节见[工作流规划](workflows.md)、[执行与证据](execution.md)和[物理检查规则](physics_guard.md)。
