# PhysicsGuard 二维物理检查

本文的直接结构检查与运行解释工具保留原有固定样例约定。第 9 步通用计划通过共享参数和几何检查接入 PhysicsGuard，并由计划工具校验所选后端，详见[单任务 YAML 说明](plans.md)。

PhysicsGuard 用代码检查输入条件和已有结果，主 Agent 根据返回的字段、证据和建议回答。当前规则针对已验证的 MoS₂ 固定晶胞样例。

## 检查规则

| 检查对象 | 规则与取值来源 |
|---|---|
| 单任务与模型配置 | 一个 optimization 任务，沿用 MatterSim 与 CPU 配置 |
| 二维设置 | YAML 的面外轴为 c，is_2d 为 true，relax_cell 为 false |
| 力阈值 | parameters.fmax 为有限正数，单位 eV/Å |
| 最大步数 | parameters.steps 为正整数 |
| 结构 | MatSimPy 读取元素、位点数、晶胞和坐标，检查有限数值及非零晶胞体积；样例输入与共享源结构作几何核对 |
| 权重 | 文件可读取，计算的 SHA-256 与配置一致 |
| 收敛 | 从记录读取原子力、广义力和 converged，沿用原入口的 generalized_fmax ≤ fmax 判据，并核对固定晶胞下的原子力判定 |
| 实际执行证据 | 对照该次 YAML、后端结果字段和最终结构，检查记录一致性 |
| 周期性 | 同时提供源结构 PBC、后端 PBC、MatSimPy 读入 PBC 与晶胞约束，逐项标明来源 |

每个问题包含 `field`、`actual`、`reason`、`suggestion`、`stage` 和 `kind`。缺失值保留为 `null`。运行编号、可用日志及已记录的失败环节随检查结果返回，历史记录未保存的失败环节标记为缺失。

检查复用原优化脚本中的几何核对和 SHA-256 函数，源结构构造及收敛核对也由共享函数提供。预览、执行前和独立优化入口使用同一套输入规则。执行工具在登记和启动后端之前检查，读取已有执行结果以及普通运行查询时均附带 PhysicsGuard 报告。

## 使用方法

在已部署环境中运行以下命令。

```bash
source /home/administrator/software/UniMatSim/.venv/bin/activate
cd /home/administrator/agent/2D-MatAgent
matagent "请用 PhysicsGuard 解释运行编号 20261120T143706Z-09f1c9a4 为什么收敛，并说明两套 PBC 与晶胞约束。"
```

检查工作区中的单个结构时，可以指定结构和 YAML。

```bash
matagent "用 PhysicsGuard 检查 examples/mos2/runs/20261120T143706Z-09f1c9a4/initial.vasp，配置使用 examples/mos2/workflow.yaml"
```

工具签名为 `physics_guard(structure_path="", run_id="", config_path="")`。结构路径与运行编号选择其中一个，路径限定在当前工作目录内。结构检查省略配置路径时使用已验证样例配置。仅从结构文件读取时，源结构 PBC 保持未知，读入 PBC 单独标注。

## 结果解释

检查区分 `converged`、`unconverged`、`failed`、`evidence_missing`，并保留尚未结束的 `running` 状态。存在矛盾的字段或产物时，结果标为证据待核对，问题列表指出具体差异。

第 2 步真实记录的阈值为 0.02 eV/Å，最终原子力与广义力均为 0.004807979334145784 eV/Å，converged 为 true，实际 2 步，上限 200 步。该次记录和后端产物一致。

源结构 PBC 为 `[true, true, false]`，后端 POSCAR 读入 PBC 为 `[true, true, true]`。c 轴为面外方向，后端使用带真空的三维周期超胞。实际 `is_2d=true`、`relax_cell=false`，优化期间固定整个晶胞。收敛支持本次势模型、晶胞约束和阈值下的局部优化力判据；热力学与动力学稳定性分别需要相对能量、参考相和声子等独立证据。局部极小点与鞍点的区分还需曲率/Hessian 等二阶信息。

## 验证命令与样例来源

运行代码检查测试。

```bash
python -m unittest discover -s tests -p 'test_physics_guard.py' -v
```

使用已配置的真实模型复跑对话验收。

```bash
MATAGENT_LIVE_TESTS=1 python -m unittest discover -s tests -p 'test_live_physics.py' -v
```

验收包含以下对象。

| 对象 | 数据性质 | 检查结果 |
|---|---|---|
| 20261120T143706Z-09f1c9a4 | 第 2 步真实运行 | 已收敛，阈值、力、后端标记及 PBC 来源可追溯 |
| illegal.yaml | 临时合成配置 | fmax = −0.015、steps = 0，均被报告为非法 |
| test-limit | 临时合成运行副本 | 2/2 步，最终力 0.05 > 0.02 eV/Å，未收敛 |
| test-missing | 临时合成运行副本 | 原子力字段缺失、广义力为 null，返回 evidence_missing |
| test-failed | 临时合成失败记录 | 保留 workflow 失败环节、错误信息与日志路径 |

临时样例由测试程序创建，并通过 `data_origin.kind=synthetic` 标明来源。测试结束后临时目录自动清理。真实模型答复、工具调用和检查报告汇总保存在本机 `.matagent/acceptance/step5.json`。非法参数还经过预览与执行入口测试，确认后端调用次数为零。验收前后比较项目真实运行文件的 SHA-256。

代码位于 [physics_guard.py](../src/matagent/physics_guard.py)，入口回归位于 [test_physics_guard.py](../tests/test_physics_guard.py)，真实模型验收位于 [test_live_physics.py](../tests/test_live_physics.py)。
