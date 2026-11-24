# MoS₂ 单结构优化

此样例从 MatSimPy 的 [MoS₂ 单层测试](../../matsimpy/tests/symmetry/test_kpath_2d.py) 中复用三个原子的元素、位点次序和分数坐标，用 UniMatSim 的 `workflow run` 执行一个 YAML 优化任务。

在当前 WSL Ubuntu 中，从任意目录执行以下一条命令。

```bash
/home/administrator/software/UniMatSim/.venv/bin/python /home/administrator/agent/2D-MatAgent/examples/mos2/run.py
```

默认使用样例目录的 [workflow.yaml](../examples/mos2/workflow.yaml)。若需调整步数或力阈值，可复制配置并在同一命令末尾加 `--config /path/to/workflow.yaml`。运行程序从相邻的两个源码仓库导入 MatSimPy 和 UniMatSim，并使用指定的解释器启动 `python -m unimatsim workflow run -C workflow.yaml -i initial.vasp -O backend --id <运行编号>`。每次运行都会在 `runs/` 下创建独立目录。

**结构和模型。** 初始结构取自 `test_buckled_mos2_monolayer_is_hexagonal`，面内晶格常数为 3.16 Å，真空方向为沿 z 的 c 轴，c 长 20 Å，两侧 S 到 Mo 平面的初始间距均为 1.56 Å。原始晶体采用面内周期边界；POSCAR 读入后，后端使用带真空的三维周期超胞。程序记录两处的 PBC，核对位点和晶胞，并在 10⁻⁸ Å 的绝对容差内比较坐标。YAML 中 `is_2d: true` 和 `relax_cell: false` 表示仅弛豫原子位置。示例使用本地 MatterSim 权重 `rand1-2d.pth`、CPU、BFGS、0.02 eV/Å 阈值和最多 200 步。运行前验证权重 SHA-256，文件缺失或不符时返回失败。实际加载路径可在日志中核对。

**本次实算环境。** WSL Python 3.12.3、MatSimPy 0.11.0、UniMatSim 2.1.0、MatterSim 1.2.2、PyTorch 2.11.0、ASE 3.28.0。仅使用已有安装与权重。跨机器复跑时，需要可用的 Python 环境、相邻的两个源码仓库及同一权重，可在 YAML 中指定新机器上的绝对路径。权重的长期来源和训练集未在本样例中验证。

**运行记录。** `run.json` 中的产物路径相对于该次运行目录。初始结构为 `initial.vasp`，最终 POSCAR 的路径在 `final_structure`。逐步能量、力和模型加载信息在 `workflow.log`。每次运行都保留传入后端的 YAML 副本。

| run.json 字段 | 来源与含义 |
|---|---|
| `energy_eV` | `backend/workflow_results.json` 中该结构的 `result.results.optimization.optimization_info.final_energy`，整个三原子胞的总能量 |
| `atomic_fmax_eV_per_A` | 同一个 `optimization_info` 下的 `atomic_fmax`，最终构型的最大原子力模 |
| `generalized_fmax_eV_per_A`、`converged`、`steps` | 分别取 `generalized_fmax`、`converged` 和 `n_steps`。按广义力与后端阈值 `fmax` 复核收敛 |
| `actual_backend`、`checkpoint` | 优化诊断 JSONL 中的活动计算器、设备参数和模型路径，以及运行前实测的权重 SHA-256 |
| `versions`、`source_commits`、`parameters` | 当前解释器所用的软件版本、两份源码的 Git 提交及本次 YAML 的优化参数 |
| `io_checks`、`periodicity` | 输入结构在 MatSimPy、UniMatSim 与工作流之间的读写核对，最终 POSCAR 回读核对，以及源结构和后端输入的周期性 |

进程退出码为 **0** 时表示真实计算收敛，**2** 表示后端正常返回且优化未收敛，**1** 表示执行或结果核验失败。缺失的结果量用 JSON `null` 表示，错误信息记录在 `error` 和日志中。首次实算记录见 [run.json](../examples/mos2/runs/20261120T143706Z-09f1c9a4/run.json)，原始产物见 [workflow_results.json](../examples/mos2/runs/20261120T143706Z-09f1c9a4/backend/workflow_results.json)。
