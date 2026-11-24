# 第 11 步执行覆盖与验收

“待实跑”表示已有调度路径，但本步没有该能力的真实结果。设备验收使用 CPU，依赖栏列出已知任务级依赖。每份计划在启动时重验。

| 能力 | 执行适配 | 输入 → 声明的输出 | 依赖 | 验证与限制 |
|---|---|---|---|---|
| `optimization` | 原生任务 | structure → optimized_structure, optimization_info, output_file | 公共运行环境 | 真实 CPU 优化 |
| `single_point` | 原生任务 | structure → energy, forces, stress | 公共运行环境 | 真实 CPU 能量、力和应力 |
| `phonon` | 原生任务 | structure → result, output_file | phonopy ✓ | 待实跑 |
| `elastic` | 原生任务 | structure → result, is_stable, output_file | ase ✓, pymatgen ✓ | 待实跑 |
| `molecular_dynamics` | 原生任务 | structure → trajectory_file, structure, final_energy | 公共运行环境 | 待实跑 |
| `eos` | 原生任务 | structure → result, output_file | 公共运行环境 | 待实跑 |
| `symmetry` | 原生任务 | structure → screening_passed, symmetry_info | 公共运行环境 | 真实隔离进程分析 |
| `bte` | 原生任务 | structure → result, hdf5_file | phono3py 缺失 | 本机缺少 phono3py，热导率待验 |
| `vasp_extract` | 原生任务 | vasp_directory → extraction_results | 公共运行环境 | 待实跑 |
| `data.import_vasp` | 固定 CLI／callback | input → stdout, output_dir | 公共运行环境 | 待实跑 |
| `data.import_poscar` | 固定 CLI／callback | input → stdout, output_dir | 公共运行环境 | 待实跑 |
| `data.import_cif` | 固定 CLI／callback | input → stdout, output_dir | 公共运行环境 | 待实跑 |
| `data.import_xyz` | 上游无实际输出 | input → stdout, output_dir | 公共运行环境 | 上游未实现可核对的输出 |
| `data.export_json` | 固定 CLI／callback | input → stdout, output | 公共运行环境 | 临时输入与真实 CLI |
| `data.export_csv` | 固定 CLI／callback | input → stdout, output | 公共运行环境 | 待实跑 |
| `data.export_cif` | 固定 CLI／callback | input → stdout, output_dir | 公共运行环境 | 真实 CLI 导出 CIF |
| `data.export_poscar` | 固定 CLI／callback | input → stdout, output_dir | 公共运行环境 | 待实跑 |
| `data.convert_to_cif` | 固定 CLI／callback | input → stdout, output, output_dir | 公共运行环境 | 待实跑 |
| `data.convert_to_poscar` | 固定 CLI／callback | input → stdout, output, output_dir | 公共运行环境 | 待实跑 |
| `data.convert_to_json` | 固定 CLI／callback | input → stdout, output, output_dir | 公共运行环境 | 待实跑 |
| `data.convert_to_xyz` | 固定 CLI／callback | input → stdout, output, output_dir | 公共运行环境 | 待实跑 |
| `data.slide` | 固定 CLI／callback | material → stdout, groups | 公共运行环境 | 临时空数据，实际 CLI 与分支失败传播 |
| `data.query_list` | 固定 CLI／callback | directory → stdout | 公共运行环境 | 待实跑 |
| `data.query_stats` | 固定 CLI／callback | directory → stdout | 公共运行环境 | 待实跑 |
| `analysis.symmetry_analyze` | 固定 CLI／callback | input → stdout, output | 公共运行环境 | 真实 CLI 读取导出的目录 |
| `analysis.symmetry_filter` | 固定 CLI／callback | input → stdout, output_dir | 公共运行环境 | 待实跑 |
| `analysis.compare_module` | 固定 CLI／callback | input → stdout, output, output_json | matplotlib ✓ | 待实跑 |
| `analysis.report_summary` | 固定 CLI／callback | input → stdout, output | 公共运行环境 | 待实跑 |
| `model.benchmark_models` | 执行前阻断 | input → stdout, output | 公共运行环境 | 自行选择内置权重且只评估首个结构，无法绑定本地检查点 |
| `model.fine_tune_model` | 本地 MatterSim CPU 训练 | material, name → stdout, output_dir | torch ✓ | 模拟训练返回及检查点契约，实际训练待验 |
| `calc.stability_check` | 执行前阻断 | input → stdout, output | 公共运行环境 | 组合入口丢失子任务失败细节，thermal 缺少本地实现 |
| `data.query_search` | 上游无实际输出 | directory → 无 | 公共运行环境 | 上游未实现可核对的输出 |
| `analysis.compare_structures` | 上游无实际输出 | input → 无 | 公共运行环境 | 上游未实现可核对的输出 |
| `analysis.visualize_structure` | 上游无实际输出 | input → 无 | 公共运行环境 | 上游未实现可核对的输出 |
| `analysis.visualize_phonon` | 上游无实际输出 | input → 无 | 公共运行环境 | 上游未实现可核对的输出 |
| `analysis.visualize_dos` | 上游无实际输出 | input → 无 | 公共运行环境 | 上游未实现可核对的输出 |
| `analysis.visualize_elastic` | 上游无实际输出 | input → 无 | 公共运行环境 | 上游未实现可核对的输出 |
| `analysis.visualize_trajectory` | 上游无实际输出 | input → 无 | 公共运行环境 | 上游未实现可核对的输出 |
| `analysis.report_detailed` | 上游无实际输出 | input → 无 | 公共运行环境 | 上游未实现可核对的输出 |
| `structure.create_structure` | 固定 Python 方法 | coords → structure | 公共运行环境 | 待实跑 |
| `structure.modify_structure` | 固定 Python 方法 | structure → structure | 公共运行环境 | 待实跑 |
| `structure.get_structure_info` | 固定 Python 方法 | structure → result | 公共运行环境 | 混合图消费真实优化产物 |
| `structure.structure_to_ase_atoms` | 固定 Python 方法 | structure → atoms | 公共运行环境 | 待实跑 |
| `structure.ase_atoms_to_structure` | 固定 Python 方法 | atoms → structure | 公共运行环境 | 待实跑 |
| `transport.calculate_thermal_conductivity` | 固定 Python 方法 | phonon_data → result | 公共运行环境 | 待实跑 |
| `transport.calculate_electronic_transport` | 固定 Python 方法 | band_structure → result | 公共运行环境 | 待实跑 |
| `transport.calculate_thermoelectric_properties` | 固定 Python 方法 | phonon_data, band_structure → result | 公共运行环境 | 待实跑 |
| `trajectory.select_frame` | 固定 Python 方法 | trajectory, reference_structure → structure | 公共运行环境 | 临时 ASE 轨迹，实际选帧接口 |

本地势需要真实且有效的加载记录。GPU、远程调度及未经验证的内置缓存会在执行前被拦截。训练入口目前接入 MatterSim CPU，要求本地基础权重和有参考能量的 extxyz，只有实际生成的非空检查点才能作为训练产物。其余训练后端仍限于规划。

## 本机证据

验收目录为项目内的 `.matagent/acceptance/step11/`。其中 workspace/runs/<run_id>/ 保存每次执行。

| 验收 | 运行编号 | 证据 |
|---|---|---|
| 新单任务通用优化 | 20261123T112222Z-c2759be06982 | artifacts/optimization/node.json |
| 优化 → 单点与结构分析 | 20261123T163008Z-4e7904ec6b9d | delivery.json、acceptance-chat.txt、acceptance-resume.txt |
| 隔离进程原生图，优化 → 单点与对称性 | 20261123T162210Z-64d81c7ec8b3 | isolated-native.json |
| 无势模型，导出 CIF → 对称性分析 | 20261123T162927Z-d5ade1b6b9d7 | cli-run.json |

优化的广义最大力与 0.03 eV/Å 阈值比较。这个结果支持指定模型与约束下的局部几何收敛，不能单独确立材料的动力学或热力学稳定性。

## 源码依据

原生图由 UniMatSim 的 workflow.run_workflow 解析并进入 WorkflowManager。stage_driver 仅在本次工作流进程中替换串行阶段循环，各节点继续由 _execute_single_task 和 resolve_bindings 处理。混合图按已保存的拓扑调用原生节点、固定 Typer 命令或公开 Python 方法。代码入口为 `src/matagent/execution/` 下的 `runner.py`、`worker.py` 和 `checks.py`。

## 回归与失败传播

项目完整套件发现 117 项，110 项通过，7 项为默认跳过的可选联调。实际 DeepSeek 对话与恢复单独执行。UniMatSim 原有失败检查点和非收敛语义测试通过 2 项。日志分别为 tests-final.log、upstream-tests.log。

模拟输入的分支运行 20261123T164319Z-fbe419bfba10 中，split 没有产生分组文件，节点失败；consumer 因顺序依赖阻断；independent 正常完成结构分析。根状态为 partial_failure。运行证据见 synthetic-failure.json。
