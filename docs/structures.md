# 第 7 步：自然语言二维结构建模

本阶段通过现有终端 Agent 调用 MatSimPy 完成结构创建、导入和编辑，使用稳定的结构编号保存多轮上下文。几何建模不加载机器学习势、不启动材料计算。语言模型负责理解请求和选择工具，坐标变换、等价性判断、文件校验由代码执行。

## 启动与完整对话

在本机 WSL Ubuntu 中执行：

```bash
source /home/administrator/software/UniMatSim/.venv/bin/activate
cd /home/administrator/agent/2D-MatAgent
matagent --new
```

逐句输入：

```text
用项目已有原型建立一个 MoS₂ 单层，采用默认参数。
把刚才的结构扩成 3×3×1 超胞。
把其中一个 Mo 换成 W；如果 Mo 位点都等价，就选固定代表并告诉我编号。
设置总真空间隙 20 Å。
导出刚才的结构为 POSCAR。
/exit
```

恢复同一个会话，再核对来源和文件：

```bash
matagent --resume <会话编号> "刚才替换的是哪个位点？替换前后的结构编号和导出文件在哪里？"
```

结构修改生成新编号，原结构保留。导出和查询不产生新的几何版本。有多个候选结构时需要指定编号；位点编号从 **1** 开始。新结构现可接入[单任务 YAML 计划](plans.md)，实际计算执行尚未接入；不会自动执行原有固定 MoS₂ 样例。

## 参考原型与来源

源码来源均为本地 MatSimPy 仓库，对应提交 `d4bd33ba608b3dbf9253340b62a7ee45719c793e`。常量保存在 [structures/tools.py](../src/matagent/structures/tools.py)，创建记录保留来源路径和提交。以下为参考几何，未声称是本次优化的产物。

| 原型标识 | 默认 a / c（Å） | 位点与来源 |
|---|---|---|
| `mos2` | 3.16 / 20 | Mo(1/3,2/3,0.5)，S(2/3,1/3,0.578)、S(2/3,1/3,0.422)；`tests/symmetry/test_kpath_2d.py::test_buckled_mos2_monolayer_is_hexagonal` |
| `graphene` | 2.46 / 20 | 两个 C，分数坐标 (1/3,2/3,0.5)、(2/3,1/3,0.5)；`tests/symmetry/test_kpath_2d.py::test_graphene_has_no_out_of_plane_points` |
| `hbn` | 2.50 / 20 | B、N，分数坐标同上；`examples/builders_nanostructure.py::hbn` |

MoS₂ 与石墨烯来源显式使用 PBC `[true,true,false]`。h-BN 原示例的 PBC 是 `[true,true,true]`，本项目单层原型显式声明 `[true,true,false]`；来源与声明分别记录，不改写来源。三个原型的面外轴均为 c。其他化学式需要有来源的结构文件，不根据化学式编造坐标。

## 导入用户文件

例如：

```text
导入二维单层结构 /home/me/structures/POSCAR，面外轴为 c。
导入结构 /mnt/c/Users/me/structures/graphene.cif。
```

支持 POSCAR、CIF 和 MatSimPy JSON。外部文件必须是用户在当前请求中明确给出的 WSL 可读路径；原文件只读，项目保存原始字节快照、原始路径和 SHA-256。不要把 Windows 反斜杠路径直接传给 WSL 入口，可使用对应的 `/mnt/c/...` 路径。

PBC 按四个字段分别表达：

| 字段 | 含义 |
|---|---|
| `source_pbc` | 文件或原型本身表达的周期性。POSCAR/CIF 没有二维 PBC 信息时为 `null` |
| `reader_pbc` | MatSimPy 文件读取结果。POSCAR 通常读为三维周期，不代表用户已声明二维 |
| `declared_pbc` | 导入请求或单层原型的显式二维声明 |
| `effective_pbc` | 当前结构实际保存的周期性 |

未明确二维条件的导入可以保存和查看，二维编辑会指出需要补充的条件。带 PBC 的完整 JSON 可保留其信息；对没有该信息的文件，可重新导入并明确“二维单层、面外轴 c”。这些字段不表示 ASE 或 UniMatSim 的后端读入状态；本阶段没有把新结构交给计算后端。

## 编辑约定与校验

- 二维编辑要求有效 PBC 为 `[true,true,false]`、面外轴为 c，且 c 垂直于 a–b 平面。超胞倍数为正整数 `[nx,ny,1]`。
- “20 Å 真空”表示**相邻周期像之间的总空隙**。材料居中，每侧 10 Å；晶胞高度等于材料厚度加 20 Å。默认 MoS₂ 厚度约 3.12 Å，所以设置后 c 约为 23.12 Å，默认 c=20 Å 时空隙则为 16.88 Å。
- 沿 c 跨边界的单层先用唯一最大空隙展开，再计算厚度并居中。最大空隙不唯一、无法可靠识别单层时返回问题，要求明确输入结构。
- 自动选点使用 `spglib.get_symmetry_layerdataset`，`aperiodic_dir=2`、`symprec=1e-5 Å`。仅当被替换元素只有一个二维等价类时选择最小位点编号；有多个类时返回代表编号和各类数量，请用户指定。
- 带额外位点属性或约束时，不自动判断可替换的等价类；用户须明确位点编号。当前环境使用已有 spglib 2.7.0。
- JSON 保存完整结构与属性；导出支持 POSCAR 和 JSON。导出后通过 MatSimPy 回读，核对元素顺序、原子数、晶胞和坐标，容差 `1e-8 Å`。只允许在实际周期方向折回等价坐标；面外非周期方向不折回。
- POSCAR 不保存二维 PBC 声明，须同时保留 `manifest.json`。导出不会覆盖其他已有文件；重复导出相同且哈希一致的产物可复用原文件。

## 工具与代码

全部工具明确返回 `starts_calculation: false`。

| 工具 | 主要参数 / 返回 |
|---|---|
| `list_structure_prototypes` | 原型、默认参数及来源 |
| `create_structure` | `prototype`，可选 `a_A`、`vacuum_gap_A` → 新结构编号 |
| `import_structure` | `source_file`、`format`、`is_2d`、`normal_axis` → 新结构编号及来源 |
| `inspect_structure` | `structure_id`、位点分页参数 → 几何、等价类、来源、父子关系、导出文件 |
| `make_structure_supercell` | `structure_id`、`repeats` → 新结构编号 |
| `substitute_structure_sites` | `structure_id`、`new_element`、`source_element`、可选 `site_numbers` → 新结构或澄清问题 |
| `set_structure_vacuum` | `structure_id`、`vacuum_gap_A` → 新结构编号 |
| `export_structure` | `structure_id`、`format`、可选 `output_file` → 路径、哈希、回读检查 |

[structures/geometry.py](../src/matagent/structures/geometry.py) 提供共享几何核对；[structures/store.py](../src/matagent/structures/store.py) 保存结构和谱系；[structures/tools.py](../src/matagent/structures/tools.py) 提供工具；[assistant/conversation.py](../src/matagent/assistant/conversation.py) 保存结构、计划、运行各自的候选引用；[assistant/agent.py](../src/matagent/assistant/agent.py) 注册工具并限制跨对象调用。旧会话缺失新增字段时使用缺省值，保留原运行查询能力。

## 产物与追溯

```text
.matagent/structures/<structure_id>/
├── structure.json       # MatSimPy 完整结构
├── manifest.json        # 来源、操作、父结构、PBC、哈希
├── source.*             # 外部导入的源文件快照（如有）
├── exports.json         # 导出登记与回读核对（如有）
└── exports/             # 默认导出位置（如有）
```

`parent_id` 是当前结构的直接父结构。经过真空调整后，若追问先前替换操作，应查看 `last_substitution.input_structure_id` 与 `output_structure_id`；它们分别表示替换前和替换后的结构，与当前结构的直接父结构概念不同。`lineage` 最多返回 20 层，超过会明确标记截断。

原生消息和工具轨迹仍保存于 `.matsimpy/sessions/`，结构引用及工具结果保存在 `.matagent/sessions/`。迁移会话时应一起保留结构、导出文件和相关会话文件。这些运行时产物已加入 Git 忽略规则。

## 本机真实验收

使用本地已配置的 `deepseek-v4-pro`，通过正式 `matagent` 终端入口完成建模、导出、退出恢复和来源查询。未安装新依赖、下载模型或启动优化。

| 项目 | 实际结果 |
|---|---|
| 建模会话 | `20261121-141357-5a7e` |
| 最终结构 | `str-20261121T141417Z-158d7446f8a6` |
| 替换输入 | `str-20261121T141405Z-25e5012a536f` |
| 替换输出 / 当前直接父结构 | `str-20261121T141412Z-941e0bf9f74c` |
| 组成 / 位点 | 27 个原子，Mo₈WS₁₈；第 1 位点 Mo → W |
| 几何 | 材料厚度约 3.12 Å，晶胞高度约 23.12 Å，总真空间隙 20 Å |
| 导出回读 | 晶胞误差 0；最大位点误差约 `5.26e-16 Å` |
| 其他来源会话 | `20261121-141438-ad7e`；真实创建石墨烯、h-BN 并导入外部 MoS₂ 文件 |
| 材料计算 | 无新运行，原有运行与计划文件哈希不变 |

最终 [POSCAR](../.matagent/structures/str-20261121T141417Z-158d7446f8a6/exports/POSCAR) 的 SHA-256 为 `e13d53703069fab171da50bdf6a21b50ab87827ac2da80360d70d81da841957f`。外部导入验收使用原真实 MoS₂ 初始结构的临时副本；测试结束后临时路径删除，项目内来源快照保留。

完整对话、工具参数和结果见本机 [report.json](../.matagent/acceptance/step7/report.json)，原始终端输出为同目录的 `initial.txt`、`resume.txt` 和 `sources.txt`。首次回答中曾混用建模与后端 PBC 术语，并混淆替换输入与当前父结构；已调整提示并增加明确字段，原始记录保留。修正后的真实复核见 [supplemental.json](../.matagent/acceptance/step7/supplemental.json)，覆盖多个不等价位点的澄清、不存在的结构编号、替换谱系和 PBC 来源。四次追问均未改变结构、运行和计划文件。

可直接恢复本次真实会话：

```bash
matagent --resume 20261121-141357-5a7e "查看结构 str-20261121T141417Z-158d7446f8a6，替换前后的结构编号和导出文件在哪里？"
```

## 验证命令

离线回归，使用临时文件和可注入模型：

```bash
python -m unittest discover -s tests -v
```

在已配置真实语言模型的环境验证原有只读查询：

```bash
MATAGENT_LIVE_TESTS=1 python -m unittest discover -s tests -v
```

仅运行真实建模对话验收（会生成结构并调用语言模型，但不启动材料计算）：

```bash
MATAGENT_LIVE_STRUCTURES=1 python -m unittest discover -s tests -p test_live_structures.py -v
```

新增测试位于 `tests/test_structures.py`、`tests/test_structure_conversation.py` 和 `tests/test_live_structures.py`，涵盖几何、来源、属性保留、澄清、错误编号、导出限制、多轮恢复及禁止误用固定计算样例。最终回归输出保存在 `.matagent/acceptance/step7/final-tests.txt`。

本轮最终离线回归为 **46 项通过、4 项按开关跳过**。另行完成 1 项真实建模集成测试、1 项真实运行查询测试、1 项真实 PhysicsGuard 测试，以及 4 个补充真实对话场景。真实优化验收开关本轮未开启。汇总见本机 [delivery.json](../.matagent/acceptance/step7/delivery.json)。

回归中修复了相同文件时间戳导致最近会话排序不确定的问题；引用文件新增保存时间，旧会话仍兼容。指定运行编号不存在时，模型直接说明缺项，不追加搜索其他编号。失败前的日志保留以便追溯，最终离线结果见 [final-tests.txt](../.matagent/acceptance/step7/final-tests.txt)，真实查询复核见 [live-query-test.txt](../.matagent/acceptance/step7/live-query-test.txt)。

## 当前边界

当前支持上述三种参考原型和用户提供的受支持格式，二维编辑限明确的 c 面外方向。没有实现任意未知材料坐标生成、缺陷能或稳定性评价。本文记录第 7 步建模能力。当前第 8、9 步已支持本地势模型选择与单任务 YAML 编译；多任务 DAG 和新结构计算执行尚未接入。原有固定 MoS₂ 优化入口继续保留。
