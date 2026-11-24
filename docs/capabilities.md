# UniMatSim 能力与参数覆盖

运行适配器、实测状态及限制见 [第 11 步执行覆盖表](execution.md)。


此表由当前工作区源码静态提取，完整机器可读定义见 [capabilities.json](capabilities.json)。九类原生任务均由实际 UniMatSim 解析器验证；独立接口编译为固定调用描述，不能交给原生 workflow run 整体执行。

“已接入”指发现、结构化参数、配置生成和相应静态校验；不表示本机计算、训练或模型精度验收通过。依赖检查仅覆盖列出的包；未列出的可选/后端依赖仍需执行前核查。

| 能力编号 | 接入 | 生成方式 | 参数数 | 本机依赖检查 |
|---|---|---|---:|---|
| `optimization` | 已接入配置 | unimatsim_task | 20 | 未做完整运行依赖探测 |
| `single_point` | 已接入配置 | unimatsim_task | 3 | 未做完整运行依赖探测 |
| `phonon` | 已接入配置 | unimatsim_task | 27 | phonopy: 已安装 3.5.0 |
| `elastic` | 已接入配置 | unimatsim_task | 16 | ase: 已安装 3.28.0, pymatgen: 已安装 2026.3.23 |
| `molecular_dynamics` | 已接入配置 | unimatsim_task | 10 | 未做完整运行依赖探测 |
| `eos` | 已接入配置 | unimatsim_task | 12 | 未做完整运行依赖探测 |
| `symmetry` | 已接入配置 | unimatsim_task | 7 | 未做完整运行依赖探测 |
| `bte` | 已接入配置 | unimatsim_task | 19 | phono3py: 缺少 |
| `vasp_extract` | 已接入配置 | unimatsim_task | 8 | 未做完整运行依赖探测 |
| `data.import_vasp` | 已接入配置 | fixed_cli_adapter | 8 | 未做完整运行依赖探测 |
| `data.import_poscar` | 已接入配置 | fixed_cli_adapter | 8 | 未做完整运行依赖探测 |
| `data.import_cif` | 已接入配置 | fixed_cli_adapter | 5 | 未做完整运行依赖探测 |
| `data.import_xyz` | 已接入配置 | fixed_cli_adapter | 4 | 未做完整运行依赖探测 |
| `data.export_json` | 已接入配置 | fixed_cli_adapter | 4 | 未做完整运行依赖探测 |
| `data.export_csv` | 已接入配置 | fixed_cli_adapter | 3 | 未做完整运行依赖探测 |
| `data.export_cif` | 已接入配置 | fixed_cli_adapter | 2 | 未做完整运行依赖探测 |
| `data.export_poscar` | 已接入配置 | fixed_cli_adapter | 2 | 未做完整运行依赖探测 |
| `data.convert_to_cif` | 已接入配置 | fixed_cli_adapter | 4 | 未做完整运行依赖探测 |
| `data.convert_to_poscar` | 已接入配置 | fixed_cli_adapter | 4 | 未做完整运行依赖探测 |
| `data.convert_to_json` | 已接入配置 | fixed_cli_adapter | 4 | 未做完整运行依赖探测 |
| `data.convert_to_xyz` | 已接入配置 | fixed_cli_adapter | 4 | 未做完整运行依赖探测 |
| `data.slide` | 已接入配置 | fixed_cli_adapter | 2 | 未做完整运行依赖探测 |
| `data.query_list` | 已接入配置 | fixed_cli_adapter | 3 | 未做完整运行依赖探测 |
| `data.query_stats` | 已接入配置 | fixed_cli_adapter | 1 | 未做完整运行依赖探测 |
| `analysis.symmetry_analyze` | 已接入配置 | fixed_cli_adapter | 4 | 未做完整运行依赖探测 |
| `analysis.symmetry_filter` | 已接入配置 | fixed_cli_adapter | 5 | 未做完整运行依赖探测 |
| `analysis.compare_module` | 已接入配置 | fixed_cli_adapter | 5 | matplotlib: 已安装 3.10.8 |
| `analysis.report_summary` | 已接入配置 | fixed_cli_adapter | 3 | 未做完整运行依赖探测 |
| `model.benchmark_models` | 已接入配置 | fixed_cli_adapter | 4 | 未做完整运行依赖探测 |
| `model.fine_tune_model` | 已接入配置 | fixed_cli_adapter | 19 | torch: 已安装 2.11.0 |
| `calc.stability_check` | 已接入配置 | fixed_cli_adapter | 19 | 未做完整运行依赖探测 |
| `data.query_search` | 上游占位/仅提示 | 无 | 3 | 未做完整运行依赖探测 |
| `analysis.compare_structures` | 上游占位/仅提示 | 无 | 2 | 未做完整运行依赖探测 |
| `analysis.visualize_structure` | 上游占位/仅提示 | 无 | 2 | 未做完整运行依赖探测 |
| `analysis.visualize_phonon` | 上游占位/仅提示 | 无 | 3 | 未做完整运行依赖探测 |
| `analysis.visualize_dos` | 上游占位/仅提示 | 无 | 2 | 未做完整运行依赖探测 |
| `analysis.visualize_elastic` | 上游占位/仅提示 | 无 | 2 | 未做完整运行依赖探测 |
| `analysis.visualize_trajectory` | 上游占位/仅提示 | 无 | 3 | 未做完整运行依赖探测 |
| `analysis.report_detailed` | 上游占位/仅提示 | 无 | 2 | 未做完整运行依赖探测 |
| `structure.create_structure` | 已接入配置 | fixed_python_adapter | 4 | 未做完整运行依赖探测 |
| `structure.modify_structure` | 已接入配置 | fixed_python_adapter | 10 | 未做完整运行依赖探测 |
| `structure.get_structure_info` | 已接入配置 | fixed_python_adapter | 0 | 未做完整运行依赖探测 |
| `structure.structure_to_ase_atoms` | 已接入配置 | fixed_python_adapter | 0 | 未做完整运行依赖探测 |
| `structure.ase_atoms_to_structure` | 已接入配置 | fixed_python_adapter | 0 | 未做完整运行依赖探测 |
| `transport.calculate_thermal_conductivity` | 已接入配置 | fixed_python_adapter | 4 | 未做完整运行依赖探测 |
| `transport.calculate_electronic_transport` | 已接入配置 | fixed_python_adapter | 4 | 未做完整运行依赖探测 |
| `transport.calculate_thermoelectric_properties` | 已接入配置 | fixed_python_adapter | 5 | 未做完整运行依赖探测 |
| `trajectory.select_frame` | 已接入配置 | fixed_python_adapter | 1 | 未做完整运行依赖探测 |

## 参数与来源

默认值为 null 且 default_expression 是符号/条件时，表示后端按输入计算。未显式指定的默认值保留在计划 backend_defaults 中，YAML 不替后端猜算动态默认。单位栏未标注的字段需结合原接口含义，不做单位换算猜测。

### `optimization`

输入：`{"structure": "structure"}`。预期输出：`{"optimized_structure": "structure", "optimization_info": "result", "output_file": "file"}`。

- 晶胞优化需应力能力；pressure_gpa 与二维面内压力需要一致的厚度换算。
- optimizer 由 ASE 公开优化器解析；未知优化器不能利用后端 BFGS 回退隐藏错误。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `save_json` | boolean | `true` | 接口未单独标注 | 否 |
| `save_structure` | string_or_array | `"vasp"` | 接口未单独标注 | 否 |
| `save_figure` | boolean | `false` | 接口未单独标注 | 否 |
| `save_summary` | boolean | `true` | 接口未单独标注 | 否 |
| `optimization_monitor` | object | `null` | 接口未单独标注 | 否 |
| `distance_monitor` | object | `null` | 接口未单独标注 | 否 |
| `resource_diagnostics` | boolean | `false` | 接口未单独标注 | 否 |
| `ignore_atom_constraints` | boolean | `false` | 接口未单独标注 | 否 |
| `is_2d` | boolean | `null` | 接口未单独标注 | 否 |
| `detect_2d_vacuum_threshold` | number | `0.1` | 接口未单独标注 | 否 |
| `pressure_gpa` | number | `null` | GPa | 否 |
| `pressure_2d_n_per_m` | number | `null` | N/m | 否 |
| `effective_thickness_angstrom` | number | `null` | Å | 否 |
| `cell_filter_mask` | array | `[1, 1, 0, 0, 0, 1]` | 接口未单独标注 | 否 |
| `fmax` | number | `0.01` | eV/Å | 否 |
| `steps` | integer | `500` | steps | 否 |
| `optimizer` | string | `"BFGS"` | 接口未单独标注 | 否 |
| `relax_cell` | boolean | `true` | 接口未单独标注 | 否 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |
| `diagnostic_interval` | integer | `1` | steps | 否 |

源码：`UniMatSim/unimatsim/workflows/tasks/optimization.py:1`；SHA-256：`a34c6c1ab6a2f1966cfe20933d8e464a364bf9bafc2d47d045a15b11088da515`。

### `single_point`

输入：`{"structure": "structure"}`。预期输出：`{"energy": "number", "forces": "array", "stress": "array"}`。


| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `save_json` | boolean | `true` | 接口未单独标注 | 否 |
| `save_summary` | boolean | `true` | 接口未单独标注 | 否 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/workflows/tasks/single_point.py:1`；SHA-256：`eafe5dd38a3fcc609a635144ef1eeb6933f4148a7c2ff71cbce196695cdc919e`。

### `phonon`

输入：`{"structure": "structure"}`。预期输出：`{"result": "result", "output_file": "file"}`。

- 弹性前驱 is_stable=false 时原生管理器会跳过声子，这是软件筛选策略，不是普适物理结论。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `save_json` | boolean | `true` | 接口未单独标注 | 否 |
| `save_summary` | boolean | `true` | 接口未单独标注 | 否 |
| `is_2d` | boolean | `null` | 接口未单独标注 | 否 |
| `detect_2d_vacuum_threshold` | number | `0.1` | 接口未单独标注 | 否 |
| `delta` | number | `0.01` | Å | 否 |
| `check_stability` | boolean | `true` | 接口未单独标注 | 否 |
| `save_bandstructure` | boolean | `null; save_json` | 接口未单独标注 | 否 |
| `save_dos` | boolean | `null; save_json` | 接口未单独标注 | 否 |
| `custom_bz_path` | object | `null` | 接口未单独标注 | 否 |
| `filter_2d_bz_path` | boolean | `true` | 接口未单独标注 | 否 |
| `band_npoints` | integer | `100` | 接口未单独标注 | 否 |
| `path_generation_mode` | string | `"default"` | 接口未单独标注 | 否 |
| `dos_kpts` | array | `null` | 接口未单独标注 | 否 |
| `qpoint_spacing` | number | `0.02` | 接口未单独标注 | 否 |
| `dos_npts` | integer | `250` | 接口未单独标注 | 否 |
| `dos_width` | number | `0.001` | 接口未单独标注 | 否 |
| `save_phonon_plot` | boolean | `null; task_config.get('save_figure', True)` | 接口未单独标注 | 否 |
| `save_figure` | boolean | `true` | 接口未单独标注 | 否 |
| `phonon_plot_path` | string | `null` | 接口未单独标注 | 否 |
| `emax` | number | `null` | 接口未单独标注 | 否 |
| `spoints_threshold` | number | `-0.0025` | 接口未单独标注 | 否 |
| `gpoints_threshold` | number | `-0.001` | 接口未单独标注 | 否 |
| `bandstructure_path` | string | `null` | 接口未单独标注 | 否 |
| `supercell` | array | `null` | 接口未单独标注 | 否 |
| `supercell_min_length` | number_or_array | `null` | Å | 否 |
| `max_supercell_atoms` | integer | `500` | 接口未单独标注 | 否 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/workflows/tasks/phonon.py:1`；SHA-256：`b54f35813776965a47eaa66a7430a3d09f46b744b38c3f48d2e4cca3de14ff6d`。

### `elastic`

输入：`{"structure": "structure"}`。预期输出：`{"result": "result", "is_stable": "boolean", "output_file": "file"}`。

- relax_structure 默认 false；optimize_strained_positions 是应变态内部原子优化。
- 晶胞应变不是把输入优化任务的 relax_cell 原样复制。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `save_json` | boolean | `true` | 接口未单独标注 | 否 |
| `save_figure` | boolean | `true` | 接口未单独标注 | 否 |
| `save_summary` | boolean | `true` | 接口未单独标注 | 否 |
| `fmax` | number | `0.1` | eV/Å | 否 |
| `use_equilibrium` | boolean | `true` | 接口未单独标注 | 否 |
| `relax_structure` | boolean | `false` | 接口未单独标注 | 否 |
| `check_stability` | boolean | `true` | 接口未单独标注 | 否 |
| `axial_strain_set` | array | `null; AXIAL_STRAIN_LEVELS` | 接口未单独标注 | 否 |
| `shear_strain_set` | array | `null; SHEAR_STRAIN_LEVELS` | 接口未单独标注 | 否 |
| `exploit_symmetry` | boolean | `false` | 接口未单独标注 | 否 |
| `optimize_strained_positions` | boolean | `false` | 接口未单独标注 | 否 |
| `is_2d` | boolean | `null` | 接口未单独标注 | 否 |
| `cell_filter_mask` | array | `null` | 接口未单独标注 | 否 |
| `lattice_type_2d` | string | `null` | 接口未单独标注 | 否 |
| `detect_2d_vacuum_threshold` | number | `0.1` | 接口未单独标注 | 否 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/workflows/tasks/elasticity.py:1`；SHA-256：`781cf270ef371eb79d836050088957b69c4e7794a72dccbf31974abf48c73aaa`。

### `molecular_dynamics`

输入：`{"structure": "structure"}`。预期输出：`{"trajectory_file": "trajectory", "structure": "structure", "final_energy": "number"}`。

- 源码使用 MaxwellBoltzmannDistribution 初始化速度和 VelocityVerlet 积分；没有 NVT 恒温器/ensemble 参数。
- result.structure 是输入结构；末帧来自 trajectory_file，普通 XYZ 不保留晶胞，选帧需显式晶胞来源。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `save_json` | boolean | `true` | 接口未单独标注 | 否 |
| `save_trajectory` | boolean | `true` | 接口未单独标注 | 否 |
| `save_figure` | boolean | `false` | 接口未单独标注 | 否 |
| `save_summary` | boolean | `true` | 接口未单独标注 | 否 |
| `temperature` | number | `300` | K | 否 |
| `timestep` | number | `1.0` | fs | 否 |
| `steps` | integer | `1000` | steps | 否 |
| `checkpoint_interval` | integer | `100` | 接口未单独标注 | 否 |
| `workflow_id` | string | `null; f'md_{formula}'` | 接口未单独标注 | 否 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/workflows/tasks/molecular_dynamics.py:1`；SHA-256：`49862d4b982aab42df2acdcf23e81d6d9ef200d2e19253475ff67e65ae15062c`。

### `eos`

输入：`{"structure": "structure"}`。预期输出：`{"result": "result", "output_file": "file"}`。

- n_points 实现默认 9，CLI/文档的 11 不代表任务默认。
- relax_structure 默认 true；上游显式优化时需决定是否保留内部优化。二维分支为应变能曲线。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `save_json` | boolean | `true` | 接口未单独标注 | 否 |
| `save_figure` | boolean | `true` | 接口未单独标注 | 否 |
| `save_summary` | boolean | `true` | 接口未单独标注 | 否 |
| `relax_structure` | boolean | `true` | 接口未单独标注 | 否 |
| `n_points` | integer | `9` | 接口未单独标注 | 否 |
| `max_abs_strain` | number | `0.1` | dimensionless | 否 |
| `fmax` | number | `0.1` | eV/Å | 否 |
| `max_steps` | integer | `500` | steps | 否 |
| `optimizer` | string | `"FIRE"` | 接口未单独标注 | 否 |
| `is_2d` | boolean | `null` | 接口未单独标注 | 否 |
| `detect_2d_vacuum_threshold` | number | `0.1` | 接口未单独标注 | 否 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/workflows/tasks/eos.py:1`；SHA-256：`47538a1cf9dccbe38ecf347effff3e41e571832e68bdb9198968a756c2841294`。

### `symmetry`

输入：`{"structure": "structure"}`。预期输出：`{"screening_passed": "boolean", "symmetry_info": "result"}`。

- SpacegroupAnalyzer 的三维空间群分析，不等价于二维层群。
- screening_passed 是任务筛选结果；必须明确声明条件才能控制后继节点。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `save_json` | boolean | `true` | 接口未单独标注 | 否 |
| `target_spacegroups` | integer_array_or_string | `[]` | 接口未单独标注 | 否 |
| `tolerance` | number | `0.0001` | Å | 否 |
| `check_crystal_system` | string | `null` | 接口未单独标注 | 否 |
| `min_symmetry_operations` | integer | `null` | 接口未单独标注 | 否 |
| `output_file` | string | `null` | 接口未单独标注 | 否 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/workflows/tasks/symmetry.py:1`；SHA-256：`9ef8ceb1770d85785d45799ab583764ee0602fd20c7e674c8aa06994cea68f39`。

### `bte`

输入：`{"structure": "structure"}`。预期输出：`{"result": "result", "hdf5_file": "file"}`。

- BTETask 复用任务 calculation_ops.calculator；所选模型参数必须在该节点保留。
- 二维 supercell_size 的面外倍数须为 1，不允许后端静默修正。
- 热导由力常数计算；不能把声子 DOS 文件当作可直接复用的三阶力常数。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `save_json` | boolean | `true` | 接口未单独标注 | 否 |
| `save_summary` | boolean | `true` | 接口未单独标注 | 否 |
| `model_name` | string | `"chgnet"` | 接口未单独标注 | 否 |
| `calculation_type` | string | `"thermal"` | 接口未单独标注 | 否 |
| `temperature_range` | number_or_array | `[300, 1000, 50]` | K | 否 |
| `is_2d` | boolean | `false` | 接口未单独标注 | 否 |
| `supercell_size` | array | `null; default_supercell_size` | 接口未单独标注 | 否 |
| `convergence_tolerance` | number | `1e-06` | 接口未单独标注 | 否 |
| `method` | string | `"RTA"` | 接口未单独标注 | 否 |
| `qpoints_mesh` | array | `null; default_qpoints` | 接口未单独标注 | 否 |
| `supercell_matrix_phonon` | array | `null` | 接口未单独标注 | 否 |
| `is_isotope` | boolean | `false` | 接口未单独标注 | 否 |
| `is_symmetry` | boolean | `true` | 接口未单独标注 | 否 |
| `symprec` | number | `0.001` | 接口未单独标注 | 否 |
| `amplitude` | number | `0.03` | 接口未单独标注 | 否 |
| `n_jobs` | integer | `1` | 接口未单独标注 | 否 |
| `parallel_mode` | string | `"auto"` | 接口未单独标注 | 否 |
| `save_figure` | boolean | `true` | 接口未单独标注 | 否 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/workflows/tasks/bte.py:1`；SHA-256：`fe14ece403b559f9d0d4ecc40b9da3c9b4192aee90cbe520aadf426a80825948`。

### `vasp_extract`

输入：`{}`。预期输出：`{"extraction_results": "dataset"}`。

- 不需要结构或势模型；structure 参数在实现中未使用。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `save_json` | boolean | `true` | 接口未单独标注 | 否 |
| `vasp_directory` | string | `"."` | 接口未单独标注 | 否 |
| `file_pattern` | string | `"*"` | 接口未单独标注 | 否 |
| `output_format` | string | `"json"` | 接口未单独标注 | 否 |
| `energy_threshold` | number | `null` | eV | 否 |
| `num_processes` | integer | `1` | 接口未单独标注 | 否 |
| `output_directory` | string | `"."` | 接口未单独标注 | 否 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/workflows/tasks/vasp_extract.py:1`；SHA-256：`44bb0248a6e9bfd082d05a5bcc69931006dacad5b6318534347f57d47a97979b`。

### `data.import_vasp`

输入：`{}`。预期输出：`{"stdout": "file", "output_dir": "directory"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output_dir` | string | `"./extracted_vasp/"` | 接口未单独标注 | 否 |
| `config` | string | `null` | 接口未单独标注 | 否 |
| `pattern` | string | `"**/OUTCAR,**/vasprun.xml"` | 接口未单独标注 | 否 |
| `recursive` | boolean | `true` | 接口未单独标注 | 否 |
| `parallel` | integer | `4` | 接口未单独标注 | 否 |
| `converged_only` | boolean | `true` | 接口未单独标注 | 否 |
| `output_format` | string | `"json"` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:111`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `data.import_poscar`

输入：`{}`。预期输出：`{"stdout": "file", "output_dir": "directory"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output_dir` | string | `"./extracted_poscar/"` | 接口未单独标注 | 否 |
| `pattern` | string | `"**/POSCAR,**/CONTCAR,*.vasp"` | 接口未单独标注 | 否 |
| `recursive` | boolean | `true` | 接口未单独标注 | 否 |
| `parallel` | integer | `4` | 接口未单独标注 | 否 |
| `output_format` | string | `"json"` | 接口未单独标注 | 否 |
| `merge` | boolean | `false` | 接口未单独标注 | 否 |
| `pymatgen_format` | boolean | `true` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:177`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `data.import_cif`

输入：`{}`。预期输出：`{"stdout": "file", "output_dir": "directory"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output_dir` | string | `"./imported_cif/"` | 接口未单独标注 | 否 |
| `pattern` | string | `"*.cif"` | 接口未单独标注 | 否 |
| `recursive` | boolean | `false` | 接口未单独标注 | 否 |
| `output_format` | string | `"json"` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:255`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `data.import_xyz`

输入：`{}`。预期输出：`{"stdout": "file", "output_dir": "directory"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output_dir` | string | `"./imported_xyz/"` | 接口未单独标注 | 否 |
| `pattern` | string | `"*.xyz"` | 接口未单独标注 | 否 |
| `recursive` | boolean | `false` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:301`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `data.export_json`

输入：`{}`。预期输出：`{"stdout": "file", "output": "file"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output` | string | `"results.json"` | 接口未单独标注 | 否 |
| `pattern` | string | `"**/result.json"` | 接口未单独标注 | 否 |
| `recursive` | boolean | `true` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:330`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `data.export_csv`

输入：`{}`。预期输出：`{"stdout": "file", "output": "file"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output` | string | `"results.csv"` | 接口未单独标注 | 否 |
| `fields` | string | `"structure,model,energy,converged"` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:372`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `data.export_cif`

输入：`{}`。预期输出：`{"stdout": "file", "output_dir": "directory"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output_dir` | string | `"./exported_cif/"` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:426`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `data.export_poscar`

输入：`{}`。预期输出：`{"stdout": "file", "output_dir": "directory"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output_dir` | string | `"./exported_poscar/"` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:455`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `data.convert_to_cif`

输入：`{}`。预期输出：`{"stdout": "file", "output": "file", "output_dir": "directory"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |
| `output` | string | `null` | 接口未单独标注 | 否 |
| `recursive` | boolean | `false` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:491`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `data.convert_to_poscar`

输入：`{}`。预期输出：`{"stdout": "file", "output": "file", "output_dir": "directory"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |
| `output` | string | `null` | 接口未单独标注 | 否 |
| `recursive` | boolean | `false` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:508`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `data.convert_to_json`

输入：`{}`。预期输出：`{"stdout": "file", "output": "file", "output_dir": "directory"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |
| `output` | string | `null` | 接口未单独标注 | 否 |
| `recursive` | boolean | `false` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:521`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `data.convert_to_xyz`

输入：`{}`。预期输出：`{"stdout": "file", "output": "file", "output_dir": "directory"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |
| `output` | string | `null` | 接口未单独标注 | 否 |
| `recursive` | boolean | `false` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:534`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `data.slide`

输入：`{}`。预期输出：`{"stdout": "file", "groups": "directory"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `material` | string | `null` | 接口未单独标注 | 是 |
| `number` | integer | `null` | 接口未单独标注 | 是 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:601`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `data.query_list`

输入：`{}`。预期输出：`{"stdout": "file"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `directory` | string | `"."` | 接口未单独标注 | 否 |
| `model` | string | `null` | 接口未单独标注 | 否 |
| `limit` | integer | `20` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:688`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `data.query_stats`

输入：`{}`。预期输出：`{"stdout": "file"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `directory` | string | `"."` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:756`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `analysis.symmetry_analyze`

输入：`{}`。预期输出：`{"stdout": "file", "output": "file"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output` | string | `null` | 接口未单独标注 | 否 |
| `tolerance` | number | `0.1` | Å | 否 |
| `recursive` | boolean | `false` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/analysis.py:66`；SHA-256：`8ca367234bcf5b549e268458a9083e04415aedf6ce1c8dcda76271ff97c6e032`。

### `analysis.symmetry_filter`

输入：`{}`。预期输出：`{"stdout": "file", "output_dir": "directory"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `spacegroup` | integer | `null` | 接口未单独标注 | 是 |
| `output_dir` | string | `"./filtered/"` | 接口未单独标注 | 否 |
| `tolerance` | number | `0.1` | Å | 否 |
| `recursive` | boolean | `false` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/analysis.py:136`；SHA-256：`8ca367234bcf5b549e268458a9083e04415aedf6ce1c8dcda76271ff97c6e032`。

### `analysis.compare_module`

输入：`{}`。预期输出：`{"stdout": "file", "output": "file", "output_json": "file"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output` | string | `"module_comparison.png"` | 接口未单独标注 | 否 |
| `output_json` | string | `null` | 接口未单独标注 | 否 |
| `top_n` | integer | `15` | 接口未单独标注 | 否 |
| `file_pattern` | string | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/analysis.py:199`；SHA-256：`8ca367234bcf5b549e268458a9083e04415aedf6ce1c8dcda76271ff97c6e032`。

### `analysis.report_summary`

输入：`{}`。预期输出：`{"stdout": "file", "output": "file"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output` | string | `"report.html"` | 接口未单独标注 | 否 |
| `format` | string | `"html"` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/analysis.py:426`；SHA-256：`8ca367234bcf5b549e268458a9083e04415aedf6ce1c8dcda76271ff97c6e032`。

### `model.benchmark_models`

输入：`{}`。预期输出：`{"stdout": "file", "output": "file"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 源码只评估首个结构；config 参数在函数体中未使用，不支持所选本地权重覆盖。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output` | string | `null` | 接口未单独标注 | 否 |
| `config` | string | `null` | 接口未单独标注 | 否 |
| `models` | string | `"mattersim"` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/model.py:338`；SHA-256：`6941082e93e868fd670088f9d32f0527f9b4c082abfc1f4f0dd1ec54be2acd7a`。

### `model.fine_tune_model`

输入：`{}`。预期输出：`{"stdout": "file", "output_dir": "directory"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 支持 mattersim/chgnet/mace/sevennet/deepmd；m3gnet/orb 为 planned。
- config 是额外训练参数 JSON；需逐后端核对，不能作为任意代码执行。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `model` | string | `null` | 接口未单独标注 | 是 |
| `material` | string | `null` | 接口未单独标注 | 是 |
| `name` | string | `null` | 接口未单独标注 | 是 |
| `epochs` | integer | `100` | 接口未单独标注 | 否 |
| `batch_size` | integer | `32` | 接口未单独标注 | 否 |
| `learning_rate` | number | `0.001` | dimensionless | 否 |
| `device` | string | `"cuda"` | 接口未单独标注 | 否 |
| `config` | string | `null` | 接口未单独标注 | 否 |
| `distributed` | boolean | `false` | 接口未单独标注 | 否 |
| `num_gpus` | integer | `null` | 接口未单独标注 | 否 |
| `valid_material` | string | `null` | 接口未单独标注 | 否 |
| `valid_split` | number | `0.1` | 接口未单独标注 | 否 |
| `early_stop_patience` | integer | `10` | 接口未单独标注 | 否 |
| `wandb` | boolean | `false` | 接口未单独标注 | 否 |
| `wandb_project` | string | `"unimatsim-finetuning"` | 接口未单独标注 | 否 |
| `wandb_entity` | string | `null` | 接口未单独标注 | 否 |
| `wandb_run_name` | string | `null` | 接口未单独标注 | 否 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |
| `training_config` | object | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/model.py:511`；SHA-256：`6941082e93e868fd670088f9d32f0527f9b4c082abfc1f4f0dd1ec54be2acd7a`。

训练额外配置 `mattersim`：

| 子字段 | 类型 | 默认值 |
|---|---|---|
| `distributed` | boolean | `false` |
| `num_gpus` | integer | `null` |
| `valid_material` | string | `null` |
| `valid_split` | number | `0.1` |
| `early_stop_patience` | integer | `10` |
| `wandb` | boolean | `false` |
| `wandb_project` | string | `"unimatsim-finetuning"` |
| `wandb_entity` | string | `null` |
| `wandb_run_name` | string | `null` |
| `seed` | integer | `42` |
| `include_forces` | boolean | `true` |
| `include_stresses` | boolean | `false` |
| `re_normalize` | boolean | `false` |
| `ckpt_interval` | integer | `10` |
| `force_loss_ratio` | number | `1.0` |
| `stress_loss_ratio` | number | `0.1` |
| `step_size` | integer | `10` |

训练额外配置 `chgnet`：

| 子字段 | 类型 | 默认值 |
|---|---|---|

训练额外配置 `mace`：

| 子字段 | 类型 | 默认值 |
|---|---|---|

训练额外配置 `sevennet`：

| 子字段 | 类型 | 默认值 |
|---|---|---|
| `cutoff` | number | `5.0` |
| `preset` | string | `"fine_tune"` |
| `prebuild_graph` | boolean | `false` |
| `load_trainset_path` | string_or_array | `null` |
| `distributed` | boolean | `false` |
| `num_gpus` | integer | `null` |

训练额外配置 `deepmd`：

| 子字段 | 类型 | 默认值 |
|---|---|---|
| `backend` | string | `null` |
| `dp_backend` | string | `"pytorch"` |
| `output_model` | string | `null` |

### `calc.stability_check`

输入：`{}`。预期输出：`{"stdout": "file", "output": "file"}`。

- 独立接口计划；不是 workflow run 原生任务。输出文件仅为规划目的地，未执行时不存在。
- 适配节点的 stdout/output/output_dir 为未来执行适配器的收集契约；计划不声称文件已生成。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output` | string | `null` | 接口未单独标注 | 否 |
| `config` | string | `null` | 接口未单独标注 | 否 |
| `model` | string | `null` | 接口未单独标注 | 否 |
| `model_path` | string | `null` | 接口未单独标注 | 否 |
| `model_variant` | string | `null` | 接口未单独标注 | 否 |
| `json_output` | boolean | `false` | 接口未单独标注 | 否 |
| `figure_output` | boolean | `false` | 接口未单独标注 | 否 |
| `summary_output` | boolean | `false` | 接口未单独标注 | 否 |
| `is_2d` | string | `null` | 接口未单独标注 | 否 |
| `checks` | string | `"elastic,phonon"` | 接口未单独标注 | 否 |
| `parallel` | integer | `1` | 接口未单独标注 | 否 |
| `pattern` | string | `"*.cif,*.vasp,*.json"` | 接口未单独标注 | 否 |
| `recursive` | boolean | `false` | 接口未单独标注 | 否 |
| `checkpoint` | boolean | `false` | 接口未单独标注 | 否 |
| `skip_existing` | boolean | `false` | 接口未单独标注 | 否 |
| `remote` | boolean | `false` | 接口未单独标注 | 否 |
| `host` | string | `null` | 接口未单独标注 | 否 |
| `port` | integer | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/calc.py:1077`；SHA-256：`c955e600df4b35b603a5efb23e294449cc4e6c34a729939d759341e6be98dcfd`。

### `data.query_search`

输入：`{}`。预期输出：`{}`。

- 当前入口仅提示信息或占位，没有实现所宣称的计算/输出。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `directory` | string | `"."` | 接口未单独标注 | 否 |
| `formula` | string | `null` | 接口未单独标注 | 否 |
| `spacegroup` | integer | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/data.py:737`；SHA-256：`2d33f1a6a67dbda1cf71fd9ea8bacd2efdd365333308713ff2921f832d013c83`。

### `analysis.compare_structures`

输入：`{}`。预期输出：`{}`。

- 当前入口仅提示信息或占位，没有实现所宣称的计算/输出。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output` | string | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/analysis.py:189`；SHA-256：`8ca367234bcf5b549e268458a9083e04415aedf6ce1c8dcda76271ff97c6e032`。

### `analysis.visualize_structure`

输入：`{}`。预期输出：`{}`。

- 当前入口仅提示信息或占位，没有实现所宣称的计算/输出。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output` | string | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/analysis.py:363`；SHA-256：`8ca367234bcf5b549e268458a9083e04415aedf6ce1c8dcda76271ff97c6e032`。

### `analysis.visualize_phonon`

输入：`{}`。预期输出：`{}`。

- 当前入口仅提示信息或占位，没有实现所宣称的计算/输出。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output` | string | `null` | 接口未单独标注 | 否 |
| `output_dir` | string | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/analysis.py:375`；SHA-256：`8ca367234bcf5b549e268458a9083e04415aedf6ce1c8dcda76271ff97c6e032`。

### `analysis.visualize_dos`

输入：`{}`。预期输出：`{}`。

- 当前入口仅提示信息或占位，没有实现所宣称的计算/输出。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output` | string | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/analysis.py:388`；SHA-256：`8ca367234bcf5b549e268458a9083e04415aedf6ce1c8dcda76271ff97c6e032`。

### `analysis.visualize_elastic`

输入：`{}`。预期输出：`{}`。

- 当前入口仅提示信息或占位，没有实现所宣称的计算/输出。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output` | string | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/analysis.py:398`；SHA-256：`8ca367234bcf5b549e268458a9083e04415aedf6ce1c8dcda76271ff97c6e032`。

### `analysis.visualize_trajectory`

输入：`{}`。预期输出：`{}`。

- 当前入口仅提示信息或占位，没有实现所宣称的计算/输出。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output` | string | `null` | 接口未单独标注 | 否 |
| `fps` | integer | `10` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/analysis.py:408`；SHA-256：`8ca367234bcf5b549e268458a9083e04415aedf6ce1c8dcda76271ff97c6e032`。

### `analysis.report_detailed`

输入：`{}`。预期输出：`{}`。

- 当前入口仅提示信息或占位，没有实现所宣称的计算/输出。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `input` | string | `null` | 接口未单独标注 | 是 |
| `output` | string | `"detailed_report.pdf"` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/ui/cli/commands/analysis.py:493`；SHA-256：`8ca367234bcf5b549e268458a9083e04415aedf6ce1c8dcda76271ff97c6e032`。

### `structure.create_structure`

输入：`{}`。预期输出：`{"structure": "structure"}`。

- 只规划固定公开方法，不在预览中执行结构改动。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `lattice` | array | `null` | 接口未单独标注 | 是 |
| `species` | array | `null` | 接口未单独标注 | 是 |
| `coords` | array | `null` | 接口未单独标注 | 是 |
| `coords_are_cartesian` | boolean | `false` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/structures/operations.py:186`；SHA-256：`7c7aac17077633935443a22c8077c1a3ffd3e1ff9696ba6e23ed62d9f5f2d105`。

### `structure.modify_structure`

输入：`{"structure": "structure"}`。预期输出：`{"structure": "structure"}`。

- 只规划固定公开方法，不在预览中执行结构改动。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `operation` | string | `null` | 接口未单独标注 | 是 |
| `scale_factor` | number | `1.0` | 接口未单独标注 | 否 |
| `distance` | number | `0.01` | Å | 否 |
| `index` | integer | `null` | 接口未单独标注 | 否 |
| `new_species` | string | `null` | 接口未单独标注 | 否 |
| `species` | string | `null` | 接口未单独标注 | 否 |
| `coords` | array | `null` | 接口未单独标注 | 否 |
| `coords_are_cartesian` | boolean | `false` | 接口未单独标注 | 否 |
| `indices` | array | `[]` | 接口未单独标注 | 否 |
| `strain` | number_or_array | `null` | 接口未单独标注 | 否 |

源码：`UniMatSim/unimatsim/structures/operations.py:224`；SHA-256：`7c7aac17077633935443a22c8077c1a3ffd3e1ff9696ba6e23ed62d9f5f2d105`。

### `structure.get_structure_info`

输入：`{"structure": "structure"}`。预期输出：`{"result": "result"}`。

- 只规划固定公开方法，不在预览中执行结构改动。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|

源码：`UniMatSim/unimatsim/structures/operations.py:368`；SHA-256：`7c7aac17077633935443a22c8077c1a3ffd3e1ff9696ba6e23ed62d9f5f2d105`。

### `structure.structure_to_ase_atoms`

输入：`{"structure": "structure"}`。预期输出：`{"atoms": "ase_atoms"}`。

- 只规划固定公开方法，不在预览中执行结构改动。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|

源码：`UniMatSim/unimatsim/structures/operations.py:312`；SHA-256：`7c7aac17077633935443a22c8077c1a3ffd3e1ff9696ba6e23ed62d9f5f2d105`。

### `structure.ase_atoms_to_structure`

输入：`{"atoms": "ase_atoms"}`。预期输出：`{"structure": "structure"}`。

- 只规划固定公开方法，不在预览中执行结构改动。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|

源码：`UniMatSim/unimatsim/structures/operations.py:324`；SHA-256：`7c7aac17077633935443a22c8077c1a3ffd3e1ff9696ba6e23ed62d9f5f2d105`。

### `transport.calculate_thermal_conductivity`

输入：`{}`。预期输出：`{"result": "result"}`。

- 独立简化常寿命输运模型，不等价于 phono3py BTE；temperature_range 第三项是采样数量。
- phonon_data 需要 frequencies/velocities；band_structure 需要 energies/velocities。
- relaxation_time_model 在当前求解公式中未切换实现；只接受 constant。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `temperature_range` | array | `[100, 1000, 10]` | K/K/count | 否 |
| `doping_concentrations` | array | `null` | cm^-3 | 否 |
| `relaxation_time_model` | string | `"constant"` | 接口未单独标注 | 否 |
| `phonon_data` | object | `null` | 接口未单独标注 | 是 |

源码：`UniMatSim/unimatsim/workflows/tasks/bte.py:1`；SHA-256：`fe14ece403b559f9d0d4ecc40b9da3c9b4192aee90cbe520aadf426a80825948`。

### `transport.calculate_electronic_transport`

输入：`{}`。预期输出：`{"result": "result"}`。

- 独立简化常寿命输运模型，不等价于 phono3py BTE；temperature_range 第三项是采样数量。
- phonon_data 需要 frequencies/velocities；band_structure 需要 energies/velocities。
- relaxation_time_model 在当前求解公式中未切换实现；只接受 constant。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `temperature_range` | array | `[100, 1000, 10]` | K/K/count | 否 |
| `doping_concentrations` | array | `null` | cm^-3 | 否 |
| `relaxation_time_model` | string | `"constant"` | 接口未单独标注 | 否 |
| `band_structure` | object | `null` | 接口未单独标注 | 是 |

源码：`UniMatSim/unimatsim/workflows/tasks/bte.py:1`；SHA-256：`fe14ece403b559f9d0d4ecc40b9da3c9b4192aee90cbe520aadf426a80825948`。

### `transport.calculate_thermoelectric_properties`

输入：`{}`。预期输出：`{"result": "result"}`。

- 独立简化常寿命输运模型，不等价于 phono3py BTE；temperature_range 第三项是采样数量。
- phonon_data 需要 frequencies/velocities；band_structure 需要 energies/velocities。
- relaxation_time_model 在当前求解公式中未切换实现；只接受 constant。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `temperature_range` | array | `[100, 1000, 10]` | K/K/count | 否 |
| `doping_concentrations` | array | `null` | cm^-3 | 否 |
| `relaxation_time_model` | string | `"constant"` | 接口未单独标注 | 否 |
| `phonon_data` | object | `null` | 接口未单独标注 | 是 |
| `band_structure` | object | `null` | 接口未单独标注 | 是 |

源码：`UniMatSim/unimatsim/workflows/tasks/bte.py:1`；SHA-256：`fe14ece403b559f9d0d4ecc40b9da3c9b4192aee90cbe520aadf426a80825948`。

### `trajectory.select_frame`

输入：`{"trajectory": "trajectory", "reference_structure": "structure"}`。预期输出：`{"structure": "structure"}`。

- Agent 适配器，ASE 读指定帧后从显式参考结构恢复晶胞/PBC；检查元素与原子顺序，不进行能量或力计算。

| 参数 | 类型 | 默认值/表达式 | 单位 | 必填 |
|---|---|---|---|---|
| `index` | integer | `-1` | zero-based frame | 否 |

## 解释边界和未完成的深层校验

- TaskType 的九项与实际注册表有自动覆盖测试；独立 CLI 的导入、导出、转换、统计、比较、报告、微调和 benchmark 逐项生成配置。重复入口（quick_*、calc 对应任务、批量 load/save）归入相同能力，不当作新的科学算法。
- `data.query_search`、多项 `analysis.visualize_*`、`compare_structures`、`report_detailed` 当前只提示信息或占位，没有伪装成计算节点。
- 服务管理、全局配置写入、模型下载不是计算图节点；模型扫描、选择和项目默认沿用第 8 步工具。
- 嵌套 `custom_bz_path`、DeepMD 等训练配置中的后端对象、Buckingham 成对参数等当前做 JSON/字段/基本类型检查；其完整领域约束还需对应执行适配器验证。不能将配置通过解释为科学输入完全正确。
- MACE 等底层库透传的任意额外 kwargs 没有在 Agent 中开放；只有当前 UniMatSim 明确读取的参数进入白名单。额外库参数需要继续建立类型约束，不能靠任意 kwargs 绕过。
- 独立输运 BTECalculator 是源码中的简化常寿命模型，与 phono3py 原生 BTE 分别登记，不能混同物理精度。
- CLI 微调的 config 支持结构化 training_config 编译到 JSON。凭据字段排除；训练标签完整性、底层训练配置和基础模型加载尚未通过真实训练验证。
- 独立 benchmark 实际只评估首个结构，源码的 config 形参未消费；Agent 拒绝用它宣称选择本地权重。
- 轨迹选帧显式使用参考晶胞和 PBC，检查元素与原子顺序。原生 MD 的 structure 字段仍表示输入结构，不宣称为最后一帧。
- 所有新通用计划 execution_supported=false；执行、调度、运行恢复尚未接入。
