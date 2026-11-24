# v1 会话与交付记录

第 6 步交付了交互式终端、会话恢复、确定的计划/运行引用和 v1 文档。保留单句终端入口以及独立的 MoS₂ 优化命令。

## 启动与恢复

在本机 WSL 中：

```bash
source /home/administrator/software/UniMatSim/.venv/bin/activate
cd /home/administrator/agent/2D-MatAgent
matagent --new
```

本次真实验收会话为 `20261121-083650-ca0b`。可直接恢复并查询，不会启动计算：

```bash
matagent --resume 20261121-083650-ca0b "刚才那次用了哪个权重？"
```

`--resume last` 选择当前工作目录最近保存的会话；同时有多个会话时推荐使用明确编号。交互式命令为 `/new`、`/sessions`、`/resume <编号>`、`/exit`。使用其他工作目录时，创建和恢复均需传入同一个 `--workspace`。

## 真实五轮对话

模型为本机已配置的 DeepSeek `deepseek-v4-pro`，后端为 MatterSim、CPU、UniMatSim `workflow run`。以下为实际对话的摘录；完整工具返回和回答保存在本机验收文件中。

| 用户请求 | 实际工具 | 返回内容 |
|---|---|---|
| 按默认配置给我看 MoS₂ 优化计划 | `preview_optimization({})` | `plan-20261121T083653Z-a20504c1`；显示完整 YAML，无参数改动，fmax=0.02 eV/Å、steps=200 |
| 执行刚才的计划 | `execute_plan`，参数为上行 plan_id | `20261121T083653Z-a20504c1`；reused=false，converged |
| 为什么判为收敛或未收敛？ | `physics_guard`，参数为同一 run_id | 原子力与广义力均为 0.004807979334145784 eV/Å，低于 0.02 eV/Å；实际 2 步 |
| 最终结构文件在哪里？ | `read_run`，参数为同一 run_id | `runs/20261121T083653Z-a20504c1/backend/optimization/optimization_initial.vasp` |
| 退出后恢复，问“刚才那次用了哪个权重？” | `read_run`，参数仍为同一 run_id | `rand1-2d.pth` 的路径、SHA-256 与实际后端模型路径 |

本次真实记录：`runs/20261121T083653Z-a20504c1/run.json`。总能量为 `-15.636652946472168 eV`。

最终结构路径：`runs/20261121T083653Z-a20504c1/backend/optimization/optimization_initial.vasp`。它来自运行记录的 `final_structure` 字段；工具将其转换为相对工作目录的 `evidence.final_structure`，原始字段出处由 `evidence_sources.final_structure` 指明。

检查点路径：

```text
/home/administrator/software/models/rand1-2d.pth
```

检查点 SHA-256：

```text
de8d3f7a5c6aa89178350a58d98e15699e65e0192d366e943aa6544ba1b5beda
```

检查点取自这次 `run.json#checkpoint.path`、`run.json#checkpoint.sha256`，实际模型路径取自 `run.json#actual_backend.model_parameters.model_path`。预览 YAML 与运行目录的 YAML 字节一致。

验收前后恰好新增一条运行；原有运行文件哈希未变。退出恢复和后续查询前后，全部运行产物哈希保持一致。没有新增依赖或下载模型。

## 补充只读核对

真实模型对“把 MoS₂ 优化的力阈值设得更严格一些，只给我看计划”的答复是：

> “更严格”没有给出具体数值，我需要明确参数后才能生成计划。
>
> 你希望将力阈值 fmax 设为多少 eV/Å？

此次没有调用工具、生成计划或启动优化。程序对多个候选计划或运行也会要求选定编号；该分支用离线测试验证。

初次结构答复中，模型曾将工具返回的 `evidence.final_structure` 误称为 run.json 内的嵌套字段，文件路径本身正确。补充 `evidence_sources` 和提示后，恢复原会话再次询问，真实答复明确区分 `run.json#final_structure` 与转换后的工具路径。原始记录和补充复核均保留，便于核对。

## 状态与证据

| 能力 | 验证状态 |
|---|---|
| 查询 → 预览 → 执行 → PhysicsGuard → 产物追问 | 真实模型和真实优化通过，同一终端入口 |
| 退出进程后恢复，继续查询同一运行及权重 | 真实模型通过，运行产物哈希不变 |
| 含糊参数先澄清，仅预览不执行 | 离线回归及真实模型补充核对通过 |
| 重复工具执行、同计划跨进程重复请求 | 程序回归通过，只调用一次模拟后端 |
| 多候选澄清、新会话隔离、明确引用不能串到别的运行 | 程序回归通过 |
| 模型在计算完成后报错，恢复仍能查询原运行 | 程序回归通过，使用模拟后端和注入的故障模型 |
| 失败、未收敛、缺失结果字段 | 第 5 步记录与隔离测试样例回归通过 |
| 旧 MatSimPy 会话恢复 | 程序回归通过，从原生工具消息重建引用 |
| 跨机器环境、其他模型服务和其他权重 | 本轮未验证 |
| 超长会话、同一会话多进程同时写入、强制终止后自动续算 | 当前未实现相应管理机制 |

本轮共覆盖 **32 项离线回归、2 项真实模型只读集成测试、1 项真实优化端到端测试**。真实优化测试单独执行一次；最终全套回归启用只读模型测试，跳过这个会再次启动优化的测试。离线模拟通过和真实优化通过分别记录。

本机验收目录为 `.matagent/acceptance/step6/`：

- `report.json`：五轮问题、回答、工具参数和返回值、run_id、plan_id、checkpoint 与不重复执行的核对结果。
- `initial.txt`、`resume.txt`、`session.json`：实际终端输出及五轮会话副本。
- `supplemental.json`：参数澄清和结构来源字段的补充只读复核。
- `e2e-test.txt`、`final-tests.txt`：真实端到端与最终回归日志。

这些本机产物被 Git 忽略；本文记录了可公开复核的命令、结果与限制。

## 实现与测试入口

- [assistant/conversation.py](../src/matagent/assistant/conversation.py)：引用解析、候选消歧、已完成工具结果保存、旧会话重建。
- [assistant/agent.py](../src/matagent/assistant/agent.py)：复用 MatSimPy 原生消息与会话恢复；给模型提供本轮引用，约束明确指向的工具参数。
- [cli.py](../src/matagent/cli.py)：单句与交互式入口、新建、列出及恢复。
- [execution/run_tools.py](../src/matagent/execution/run_tools.py)：权重和产物原始字段来源。
- [test_conversation.py](../tests/test_conversation.py)：隔离的多轮与恢复回归。
- [test_live_conversation.py](../tests/test_live_conversation.py)：可显式启用的一次真实优化验收。

普通离线回归：

```bash
python -m unittest discover -s tests -v
```

真实语言模型只读回归：

```bash
MATAGENT_LIVE_TESTS=1 python -m unittest discover -s tests -v
```

重新执行真实优化端到端验收（会创建一份新计划并启动一次新优化）：

```bash
MATAGENT_LIVE_E2E=1 python -m unittest discover -s tests -p test_live_conversation.py -v
```

## 当前边界

v1 的执行对象是已验证的 MoS₂ 样例，只开放 fmax 与 steps，固定模型、设备、面外轴及晶胞约束。优化为同步调用；六轮上限限制每个用户请求的模型调用循环。终端应按顺序使用同一会话，尚未提供会话并发写锁或历史压缩。

材料任务仍由固定的 YAML 入口运行。计算进程突然终止后的自动续算未实现；已有执行登记会阻止同计划再次启动，应先检查运行状态和日志。语言模型输出存在表述波动，代码核对的数值、状态及文件证据保存在工具结果中。

力收敛只支持该势模型与约束下的力阈值判据；局部极值类型、热力学与动力学稳定性尚需其他证据。权重训练来源和跨材料适用性未在本轮验证。
