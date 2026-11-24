# 第 10 步 UniMatSim 最小接口改动

修改保留旧工作流的隐式结构选择方式；只有显式 input_bindings 的新图走严格契约。

| 文件 | 改动 |
|---|---|
| workflows/task_parser.py | 补齐 VASP_EXTRACT，透传 input_bindings/preconditions |
| workflows/builder.py | 保存绑定和前置条件；None 结构可序列化/恢复 |
| workflows/bindings.py | 纯产物解析、类型/文件检查、条件检查和副本隔离；不运行任务 |
| workflows/manager.py | 普通及隔离任务在模型加载/子进程启动前解析严格绑定；对称性/提取任务跳过模型切换 |
| workflows/isolation.py | 支持数据任务的 None 结构载荷 |
| ui/cli/commands/workflow.py | 纯提取图不要求晶体输入、不初始化模型；对称性图不加载默认模型 |
| workflows/tasks/bte.py | 将已有 BTETask 的二阶超胞、同位素、对称性容差、位移和并行参数透传；保留预加载计算器复用 |

没有修改 engine/calculations.py 或势加载 worker，因此现有模型加载证据仍可复用。解析器、builder、manager 等源码摘要变化会使旧计划的配置证据失效，不能通过覆盖摘要消除这个提醒。

测试位于 2D-MatAgent/tests/test_workflows.py：实际解析器、实际管理器和隔离载荷路径使用模拟任务/进程池；BTE 使用替身 BTETask 检查 selected calculation_ops 与参数。未调用科学求解器。另运行上游 test_workflow_reliability.py 中两个已有模拟任务测试，未运行该文件中的真实 Lennard-Jones 优化测试。

未新增科学算法。轨迹读取/选帧是 Agent 适配层的显式数据转换。后续独立操作执行器需消费同一份类型化绑定，不应把混合清单直接传给原生 workflow run。

## 第 11 步增量

workflows/stage_driver.py 提供进程上下文内的可选串行阶段回调。workflows/manager.py 的 _execute_stages 在回调存在时交给本地应用驱动，常规 CLI 使用原调度与检查点行为。workflows/isolation.py 将实际计算器、模型参数和可观察的设备随子进程结果返回。常规与隔离路径均复用原有任务实现和绑定。隔离原生图的运行证据见 [第 11 步验收](execution.md)。
